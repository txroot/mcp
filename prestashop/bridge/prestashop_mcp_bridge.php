<?php
declare(strict_types=1);

/*
 * Eletrix PrestaShop MCP bridge.
 * Read-only, fixed/allow-listed queries only. No arbitrary SQL endpoint exists.
 * Compatible with PHP 7.4+ and PrestaShop 1.7.x / MariaDB.
 */

const CONFIG_PATH = __DIR__ . '/.prestashop_orders_bridge.env';
const MAX_PAGE_SIZE = 200;

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('Pragma: no-cache');
header('X-Robots-Tag: noindex, nofollow, noarchive');
header('X-Content-Type-Options: nosniff');

function respond(int $status, array $payload): void {
    http_response_code($status);
    echo json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function is_https(): bool {
    if (!empty($_SERVER['HTTPS']) && strtolower((string)$_SERVER['HTTPS']) !== 'off') return true;
    return isset($_SERVER['HTTP_X_FORWARDED_PROTO']) && strtolower((string)$_SERVER['HTTP_X_FORWARDED_PROTO']) === 'https';
}

function load_env_file(string $path): array {
    if (!is_file($path) || !is_readable($path)) {
        respond(500, ['ok' => false, 'error' => 'Server configuration file not found/readable']);
    }
    $out = [];
    $lines = file($path, FILE_IGNORE_NEW_LINES);
    if ($lines === false) respond(500, ['ok' => false, 'error' => 'Could not read server configuration']);
    foreach ($lines as $raw) {
        $line = trim($raw);
        if ($line === '' || strpos($line, '#') === 0 || strpos($line, '=') === false) continue;
        [$key, $value] = explode('=', $line, 2);
        $key = trim($key); $value = trim($value);
        if (strlen($value) >= 2) {
            $first = $value[0]; $last = $value[strlen($value)-1];
            if (($first === '"' && $last === '"') || ($first === "'" && $last === "'")) $value = substr($value, 1, -1);
        }
        $out[$key] = $value;
    }
    return $out;
}

function require_config(array $cfg, string $key): string {
    if (!isset($cfg[$key]) || $cfg[$key] === '') respond(500, ['ok' => false, 'error' => 'Missing server configuration key', 'key' => $key]);
    return (string)$cfg[$key];
}

function int_param(string $name, int $default, int $min, int $max): int {
    $raw = isset($_GET[$name]) ? (string)$_GET[$name] : (string)$default;
    if (!preg_match('/^-?\d+$/', $raw)) respond(400, ['ok' => false, 'error' => 'Invalid integer', 'parameter' => $name]);
    $v = (int)$raw;
    if ($v < $min || $v > $max) respond(400, ['ok' => false, 'error' => 'Integer outside allowed range', 'parameter' => $name]);
    return $v;
}

function optional_int_param(string $name, int $min, int $max): ?int {
    if (!isset($_GET[$name]) || (string)$_GET[$name] === '') return null;
    return int_param($name, $min, $min, $max);
}

function resolve_date_param(string $value, string $name): string {
    $value = trim($value);
    $today = new DateTimeImmutable('today');
    if ($value === 'today') return $today->format('Y-m-d');
    if ($value === 'yesterday') return $today->modify('-1 day')->format('Y-m-d');
    if (preg_match('/^(\d{1,5})daysAgo$/', $value, $m)) {
        return $today->modify('-' . (int)$m[1] . ' days')->format('Y-m-d');
    }
    $dt = DateTime::createFromFormat('!Y-m-d', $value);
    $errors = DateTime::getLastErrors();
    if ($dt === false || ($errors !== false && ($errors['warning_count'] > 0 || $errors['error_count'] > 0)) || $dt->format('Y-m-d') !== $value) {
        respond(400, ['ok' => false, 'error' => 'Invalid date', 'parameter' => $name]);
    }
    return $value;
}

function date_range(): array {
    $from = resolve_date_param((string)($_GET['from'] ?? '30daysAgo'), 'from');
    $to = resolve_date_param((string)($_GET['to'] ?? 'today'), 'to');
    if ($from > $to) respond(400, ['ok' => false, 'error' => 'from must be <= to']);
    return [$from, $to];
}

function page_params(int $defaultLimit = 50): array {
    $page = int_param('page', 1, 1, 100000);
    $limit = int_param('limit', $defaultLimit, 1, MAX_PAGE_SIZE);
    return [$page, $limit, ($page - 1) * $limit];
}

function fetch_one(PDO $pdo, string $sql, array $params = []): array {
    $stmt = $pdo->prepare($sql); $stmt->execute($params);
    $row = $stmt->fetch();
    return is_array($row) ? $row : [];
}

function fetch_all(PDO $pdo, string $sql, array $params = []): array {
    $stmt = $pdo->prepare($sql); $stmt->execute($params);
    return $stmt->fetchAll();
}

if (!is_https()) respond(403, ['ok' => false, 'error' => 'HTTPS required']);

$cfg = load_env_file(CONFIG_PATH);
$dbHost = require_config($cfg, 'DB_HOST');
$dbPort = (int)($cfg['DB_PORT'] ?? '3306');
$dbName = require_config($cfg, 'DB_NAME');
$dbUser = require_config($cfg, 'DB_USER');
$dbPass = require_config($cfg, 'DB_PASSWORD');
$prefix = require_config($cfg, 'DB_PREFIX');
$tokenHash = strtolower(require_config($cfg, 'BRIDGE_TOKEN_SHA256'));

if (!preg_match('/^[A-Za-z0-9_]+$/', $prefix)) respond(500, ['ok' => false, 'error' => 'Invalid DB_PREFIX']);
if (!preg_match('/^[a-f0-9]{64}$/', $tokenHash)) respond(500, ['ok' => false, 'error' => 'Invalid BRIDGE_TOKEN_SHA256']);

$allowedIpsRaw = trim((string)($cfg['ALLOWED_IPS'] ?? ''));
if ($allowedIpsRaw !== '') {
    $allowedIps = array_values(array_filter(array_map('trim', explode(',', $allowedIpsRaw))));
    $remoteIp = (string)($_SERVER['REMOTE_ADDR'] ?? '');
    if (!in_array($remoteIp, $allowedIps, true)) respond(403, ['ok' => false, 'error' => 'IP not allowed']);
}

$auth = (string)($_SERVER['HTTP_AUTHORIZATION'] ?? ($_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? ''));
if (!preg_match('/^Bearer\s+(.+)$/i', $auth, $m)) respond(401, ['ok' => false, 'error' => 'Missing bearer token']);
$token = trim($m[1]);
if (!hash_equals($tokenHash, hash('sha256', $token))) respond(401, ['ok' => false, 'error' => 'Invalid bearer token']);

try {
    $dsn = sprintf('mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4', $dbHost, $dbPort, $dbName);
    $pdo = new PDO($dsn, $dbUser, $dbPass, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);
    try { $pdo->exec('SET SESSION TRANSACTION READ ONLY'); } catch (Throwable $ignored) {}

    $mode = strtolower((string)($_GET['mode'] ?? 'health'));
    $shopId = int_param('shop_id', 1, 1, 1000000);
    $langId = int_param('lang_id', 2, 1, 1000000);
    $p = $prefix;

    if ($mode === 'health') {
        $server = $pdo->query("SELECT VERSION() AS mariadb_version, DATABASE() AS selected_database, CURRENT_USER() AS authenticated_db_user")->fetch();
        $grants = [];
        foreach ($pdo->query('SHOW GRANTS FOR CURRENT_USER()') as $row) $grants[] = (string)(array_values($row)[0] ?? '');
        $required = ['orders','order_detail','order_payment','customer','order_state_lang','cart','cart_product','product','product_lang','product_attribute','stock_available','image','manufacturer','category_product','category_lang'];
        $tables = [];
        $stmt = $pdo->prepare('SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?');
        foreach ($required as $short) {
            $table = $p . $short; $stmt->execute([$dbName, $table]);
            $tables[$short] = ['table' => $table, 'exists' => ((int)$stmt->fetchColumn()) > 0];
        }
        respond(200, [
            'ok'=>true, 'mode'=>'health', 'server'=>$server, 'grants'=>$grants, 'tables'=>$tables,
            'security'=>['arbitrary_sql_supported'=>false,'write_queries_supported'=>false,'password_exposed'=>false,'fixed_queries_only'=>true],
        ]);
    }

    if ($mode === 'overview') {
        [$from,$to] = date_range();
        $orders = fetch_one($pdo, "
            SELECT COUNT(*) orders_total,
                   SUM(CASE WHEN o.valid=1 THEN 1 ELSE 0 END) orders_valid,
                   COALESCE(SUM(o.total_paid_tax_incl),0) gross_order_value_tax_incl,
                   COALESCE(SUM(o.total_paid_real),0) total_paid_real,
                   COALESCE(AVG(o.total_paid_tax_incl),0) average_order_value
            FROM `{$p}orders` o
            WHERE o.id_shop=:shop AND o.date_add>=:from_date AND o.date_add<DATE_ADD(:to_date, INTERVAL 1 DAY)
        ", ['shop'=>$shopId,'from_date'=>$from,'to_date'=>$to]);
        $states = fetch_all($pdo, "
            SELECT o.current_state state_id, COALESCE(osl.name, CONCAT('State ',o.current_state)) state_name,
                   COUNT(*) orders, COALESCE(SUM(o.total_paid_tax_incl),0) value_tax_incl
            FROM `{$p}orders` o
            LEFT JOIN `{$p}order_state_lang` osl ON osl.id_order_state=o.current_state AND osl.id_lang=:lang
            WHERE o.id_shop=:shop AND o.date_add>=:from_date AND o.date_add<DATE_ADD(:to_date, INTERVAL 1 DAY)
            GROUP BY o.current_state, osl.name ORDER BY orders DESC
        ", ['lang'=>$langId,'shop'=>$shopId,'from_date'=>$from,'to_date'=>$to]);
        $customers = fetch_one($pdo, "SELECT COUNT(*) new_customers FROM `{$p}customer` WHERE id_shop=:shop AND date_add>=:from_date AND date_add<DATE_ADD(:to_date, INTERVAL 1 DAY)", ['shop'=>$shopId,'from_date'=>$from,'to_date'=>$to]);
        $carts = fetch_one($pdo, "SELECT COUNT(*) carts_created FROM `{$p}cart` WHERE id_shop=:shop AND date_add>=:from_date AND date_add<DATE_ADD(:to_date, INTERVAL 1 DAY)", ['shop'=>$shopId,'from_date'=>$from,'to_date'=>$to]);
        $abandoned = fetch_one($pdo, "
            SELECT COUNT(*) abandoned_carts
            FROM `{$p}cart` c
            WHERE c.id_shop=:shop
              AND c.date_upd < DATE_SUB(NOW(), INTERVAL 2 HOUR)
              AND c.date_upd >= DATE_SUB(NOW(), INTERVAL 30 DAY)
              AND EXISTS (SELECT 1 FROM `{$p}cart_product` cp WHERE cp.id_cart=c.id_cart AND cp.quantity>0)
              AND NOT EXISTS (SELECT 1 FROM `{$p}orders` o WHERE o.id_cart=c.id_cart)
        ", ['shop'=>$shopId]);
        $catalog = fetch_one($pdo, "
            SELECT COUNT(*) products_total,
                   SUM(CASE WHEN p.active=1 THEN 1 ELSE 0 END) products_active,
                   SUM(CASE WHEN p.active=0 THEN 1 ELSE 0 END) products_inactive
            FROM `{$p}product` p WHERE p.id_shop_default=:shop
        ", ['shop'=>$shopId]);
        respond(200, ['ok'=>true,'mode'=>'overview','period'=>['from'=>$from,'to'=>$to],'orders'=>$orders,'order_states'=>$states,'customers'=>$customers,'carts'=>array_merge($carts,$abandoned),'catalog'=>$catalog]);
    }

    if ($mode === 'orders') {
        [$from,$to] = date_range(); [$page,$limit,$offset] = page_params(50);
        $stateId = optional_int_param('state_id', 1, 1000000);
        $validOnly = int_param('valid_only', 0, 0, 1);
        $where = "o.id_shop=:shop AND o.date_add>=:from_date AND o.date_add<DATE_ADD(:to_date, INTERVAL 1 DAY)";
        $params = ['shop'=>$shopId,'from_date'=>$from,'to_date'=>$to,'lang'=>$langId];
        if ($stateId !== null) { $where .= ' AND o.current_state=:state_id'; $params['state_id']=$stateId; }
        if ($validOnly === 1) $where .= ' AND o.valid=1';
        $countParams = $params; unset($countParams['lang']);
        $count = fetch_one($pdo, "SELECT COUNT(*) total FROM `{$p}orders` o WHERE {$where}", $countParams);
        $sql = "
            SELECT o.id_order, o.reference, o.date_add order_date, o.date_upd order_updated,
                   o.current_state state_id, COALESCE(osl.name, CONCAT('State ',o.current_state)) state_name,
                   o.valid, o.total_paid_tax_incl total, o.total_products_wt products_total_tax_incl,
                   o.total_shipping_tax_incl shipping_tax_incl, o.total_paid_real, o.payment payment_method,
                   o.invoice_number, o.invoice_date,
                   c.id_customer, NULLIF(c.company,'') customer_company,
                   TRIM(CONCAT(c.firstname,' ',c.lastname)) customer_name
            FROM `{$p}orders` o
            LEFT JOIN `{$p}order_state_lang` osl ON osl.id_order_state=o.current_state AND osl.id_lang=:lang
            LEFT JOIN `{$p}customer` c ON c.id_customer=o.id_customer
            WHERE {$where}
            ORDER BY o.date_add DESC, o.id_order DESC LIMIT {$limit} OFFSET {$offset}
        ";
        $rows = fetch_all($pdo, $sql, $params);
        respond(200, ['ok'=>true,'mode'=>'orders','period'=>['from'=>$from,'to'=>$to],'page'=>$page,'limit'=>$limit,'total'=>(int)($count['total']??0),'rows'=>$rows]);
    }

    if ($mode === 'order_details') {
        $orderId = int_param('order_id', 0, 1, 2147483647);
        $order = fetch_one($pdo, "
            SELECT o.id_order,o.reference,o.date_add order_date,o.date_upd order_updated,o.current_state state_id,
                   COALESCE(osl.name,CONCAT('State ',o.current_state)) state_name,o.valid,o.payment payment_method,o.module,
                   o.total_discounts_tax_incl,o.total_products_wt products_total_tax_incl,o.total_shipping_tax_incl,
                   o.total_paid_tax_incl total,o.total_paid_real,o.invoice_number,o.invoice_date,o.shipping_number,
                   c.id_customer,NULLIF(c.company,'') customer_company,TRIM(CONCAT(c.firstname,' ',c.lastname)) customer_name,c.email customer_email
            FROM `{$p}orders` o
            LEFT JOIN `{$p}order_state_lang` osl ON osl.id_order_state=o.current_state AND osl.id_lang=:lang
            LEFT JOIN `{$p}customer` c ON c.id_customer=o.id_customer
            WHERE o.id_order=:order_id AND o.id_shop=:shop LIMIT 1
        ", ['lang'=>$langId,'order_id'=>$orderId,'shop'=>$shopId]);
        if (!$order) respond(404, ['ok'=>false,'error'=>'Order not found']);
        $lines = fetch_all($pdo, "
            SELECT od.id_order_detail,od.product_id,od.product_attribute_id,od.product_reference,od.product_ean13,
                   od.product_name,od.product_quantity,od.product_quantity_refunded,od.unit_price_tax_incl,
                   od.total_price_tax_incl,od.original_wholesale_price
            FROM `{$p}order_detail` od WHERE od.id_order=:order_id ORDER BY od.id_order_detail
        ", ['order_id'=>$orderId]);
        respond(200, ['ok'=>true,'mode'=>'order_details','order'=>$order,'lines'=>$lines]);
    }

    if ($mode === 'abandoned_carts') {
        $minHours = int_param('min_age_hours', 2, 1, 720);
        $maxDays = int_param('max_age_days', 30, 1, 365);
        [$page,$limit,$offset] = page_params(50);
        if ($maxDays * 24 <= $minHours) respond(400, ['ok'=>false,'error'=>'max_age_days must cover a period older than min_age_hours']);
        $qualifier = "c.id_shop=:shop AND c.date_upd < DATE_SUB(NOW(), INTERVAL {$minHours} HOUR) AND c.date_upd >= DATE_SUB(NOW(), INTERVAL {$maxDays} DAY) AND EXISTS (SELECT 1 FROM `{$p}cart_product` cp0 WHERE cp0.id_cart=c.id_cart AND cp0.quantity>0) AND NOT EXISTS (SELECT 1 FROM `{$p}orders` o0 WHERE o0.id_cart=c.id_cart)";
        $count = fetch_one($pdo, "SELECT COUNT(*) total FROM `{$p}cart` c WHERE {$qualifier}", ['shop'=>$shopId]);
        $rows = fetch_all($pdo, "
            SELECT c.id_cart,c.id_customer,c.date_add cart_created,c.date_upd cart_updated,
                   TIMESTAMPDIFF(HOUR,c.date_upd,NOW()) age_hours,
                   NULLIF(cu.company,'') customer_company,
                   CASE WHEN c.id_customer>0 THEN TRIM(CONCAT(cu.firstname,' ',cu.lastname)) ELSE NULL END customer_name,
                   SUM(cp.quantity) units,
                   COUNT(DISTINCT CONCAT(cp.id_product,':',cp.id_product_attribute)) product_lines,
                   ROUND(SUM(cp.quantity * (p.price + COALESCE(pa.price,0))),2) estimated_catalog_value_ex_tax,
                   GROUP_CONCAT(DISTINCT CONCAT(cp.quantity,'x ',COALESCE(pl.name,CONCAT('Product ',cp.id_product))) ORDER BY cp.date_add SEPARATOR ' | ') products
            FROM `{$p}cart` c
            JOIN `{$p}cart_product` cp ON cp.id_cart=c.id_cart AND cp.quantity>0
            JOIN `{$p}product` p ON p.id_product=cp.id_product
            LEFT JOIN `{$p}product_attribute` pa ON pa.id_product_attribute=cp.id_product_attribute
            LEFT JOIN `{$p}product_lang` pl ON pl.id_product=cp.id_product AND pl.id_shop=:pl_shop AND pl.id_lang=:lang
            LEFT JOIN `{$p}customer` cu ON cu.id_customer=c.id_customer
            WHERE {$qualifier}
            GROUP BY c.id_cart,c.id_customer,c.date_add,c.date_upd,cu.company,cu.firstname,cu.lastname
            ORDER BY c.date_upd DESC LIMIT {$limit} OFFSET {$offset}
        ", ['pl_shop'=>$shopId,'lang'=>$langId,'shop'=>$shopId]);
        respond(200, ['ok'=>true,'mode'=>'abandoned_carts','definition'=>['min_age_hours'=>$minHours,'max_age_days'=>$maxDays,'value'=>'current catalogue estimate excluding tax, shipping and discounts'],'page'=>$page,'limit'=>$limit,'total'=>(int)($count['total']??0),'rows'=>$rows]);
    }

    if ($mode === 'products_summary') {
        $products = fetch_one($pdo, "
            SELECT COUNT(*) products_total,
                   SUM(p.active=1) products_active,SUM(p.active=0) products_inactive,
                   SUM(TRIM(COALESCE(p.reference,''))='') products_without_reference,
                   SUM(TRIM(COALESCE(p.ean13,''))='') products_without_ean,
                   SUM(p.id_manufacturer=0 OR p.id_manufacturer IS NULL) products_without_manufacturer
            FROM `{$p}product` p WHERE p.id_shop_default=:shop
        ", ['shop'=>$shopId]);
        $comb = fetch_one($pdo, "SELECT COUNT(*) combinations FROM `{$p}product_attribute` pa JOIN `{$p}product` p0 ON p0.id_product=pa.id_product WHERE p0.id_shop_default=:shop", ['shop'=>$shopId]);
        $standalone = fetch_one($pdo, "SELECT COUNT(*) standalone_products FROM `{$p}product` p0 WHERE p0.id_shop_default=:shop AND NOT EXISTS (SELECT 1 FROM `{$p}product_attribute` pa WHERE pa.id_product=p0.id_product)", ['shop'=>$shopId]);
        $images = fetch_one($pdo, "SELECT COUNT(DISTINCT i.id_product) products_with_images,COUNT(*) images_total FROM `{$p}image` i JOIN `{$p}product` p0 ON p0.id_product=i.id_product WHERE p0.id_shop_default=:shop", ['shop'=>$shopId]);
        $mfr = fetch_one($pdo, "SELECT COUNT(*) manufacturers_total,SUM(active=1) manufacturers_active FROM `{$p}manufacturer`", []);
        $skuRecords = (int)($comb['combinations']??0) + (int)($standalone['standalone_products']??0);
        respond(200, ['ok'=>true,'mode'=>'products_summary','products'=>$products,'combinations'=>$comb,'standalone'=>$standalone,'sku_records_estimate'=>$skuRecords,'images'=>$images,'manufacturers'=>$mfr]);
    }

    if ($mode === 'products_search') {
        $q = trim((string)($_GET['q'] ?? ''));
        if (strlen($q) > 200) respond(400, ['ok'=>false,'error'=>'Search query too long']);
        $active = optional_int_param('active', 0, 1);
        $limit = int_param('limit', 50, 1, 100);
        $where = 'p.id_shop_default=:shop'; $params = ['shop'=>$shopId,'lang'=>$langId,'pl_shop'=>$shopId,'cl_shop'=>$shopId];
        if ($active !== null) { $where .= ' AND p.active=:active'; $params['active']=$active; }
        if ($q !== '') {
            $like = '%' . $q . '%';
            $where .= ' AND (pl.name LIKE :q1 OR p.reference LIKE :q2 OR p.ean13 LIKE :q3 OR m.name LIKE :q4)';
            $params['q1']=$like; $params['q2']=$like; $params['q3']=$like; $params['q4']=$like;
        }
        $rows = fetch_all($pdo, "
            SELECT p.id_product,p.reference,p.ean13,p.active,p.available_for_order,p.price price_ex_tax,p.product_type,
                   pl.name,NULLIF(m.name,'') manufacturer,cl.name default_category,
                   COALESCE(sa.quantity,0) stock_quantity,
                   (SELECT COUNT(*) FROM `{$p}image` i WHERE i.id_product=p.id_product) image_count,
                   (SELECT COUNT(*) FROM `{$p}product_attribute` pa WHERE pa.id_product=p.id_product) combination_count,
                   p.date_upd
            FROM `{$p}product` p
            LEFT JOIN `{$p}product_lang` pl ON pl.id_product=p.id_product AND pl.id_shop=:pl_shop AND pl.id_lang=:lang
            LEFT JOIN `{$p}manufacturer` m ON m.id_manufacturer=p.id_manufacturer
            LEFT JOIN `{$p}category_lang` cl ON cl.id_category=p.id_category_default AND cl.id_shop=:cl_shop AND cl.id_lang=:lang2
            LEFT JOIN `{$p}stock_available` sa ON sa.id_product=p.id_product AND sa.id_product_attribute=0 AND sa.id_shop=:sa_shop
            WHERE {$where}
            ORDER BY p.active DESC,pl.name,p.id_product LIMIT {$limit}
        ", array_merge($params, ['lang2'=>$langId,'sa_shop'=>$shopId]));
        respond(200, ['ok'=>true,'mode'=>'products_search','query'=>$q,'count'=>count($rows),'rows'=>$rows]);
    }

    if ($mode === 'product_details') {
        $productId = int_param('product_id', 0, 1, 2147483647);
        $product = fetch_one($pdo, "
            SELECT p.id_product,p.reference,p.supplier_reference,p.ean13,p.isbn,p.upc,p.mpn,p.active,p.available_for_order,
                   p.visibility,p.condition,p.price price_ex_tax,p.wholesale_price,p.id_category_default,p.id_manufacturer,
                   p.weight,p.width,p.height,p.depth,p.low_stock_threshold,p.date_add,p.date_upd,
                   pl.name,pl.description,pl.description_short,pl.link_rewrite,pl.meta_title,pl.meta_description,
                   m.name manufacturer,COALESCE(sa.quantity,0) stock_quantity,COALESCE(sa.physical_quantity,0) physical_quantity,
                   COALESCE(sa.reserved_quantity,0) reserved_quantity,
                   (SELECT COUNT(*) FROM `{$p}image` i WHERE i.id_product=p.id_product) image_count,
                   (SELECT COUNT(*) FROM `{$p}product_attribute` pa WHERE pa.id_product=p.id_product) combination_count
            FROM `{$p}product` p
            LEFT JOIN `{$p}product_lang` pl ON pl.id_product=p.id_product AND pl.id_shop=:pl_shop AND pl.id_lang=:lang
            LEFT JOIN `{$p}manufacturer` m ON m.id_manufacturer=p.id_manufacturer
            LEFT JOIN `{$p}stock_available` sa ON sa.id_product=p.id_product AND sa.id_product_attribute=0 AND sa.id_shop=:sa_shop
            WHERE p.id_product=:product_id AND p.id_shop_default=:shop LIMIT 1
        ", ['pl_shop'=>$shopId,'lang'=>$langId,'sa_shop'=>$shopId,'product_id'=>$productId,'shop'=>$shopId]);
        if (!$product) respond(404, ['ok'=>false,'error'=>'Product not found']);
        $categories = fetch_all($pdo, "
            SELECT cp.id_category,cl.name FROM `{$p}category_product` cp
            LEFT JOIN `{$p}category_lang` cl ON cl.id_category=cp.id_category AND cl.id_shop=:shop AND cl.id_lang=:lang
            WHERE cp.id_product=:product_id ORDER BY cl.name
        ", ['shop'=>$shopId,'lang'=>$langId,'product_id'=>$productId]);
        $combinations = fetch_all($pdo, "
            SELECT pa.id_product_attribute,pa.reference,pa.ean13,pa.price price_impact,pa.weight weight_impact,pa.default_on,
                   COALESCE(sa.quantity,0) stock_quantity
            FROM `{$p}product_attribute` pa
            LEFT JOIN `{$p}stock_available` sa ON sa.id_product_attribute=pa.id_product_attribute AND sa.id_shop=:shop
            WHERE pa.id_product=:product_id ORDER BY pa.id_product_attribute LIMIT 200
        ", ['shop'=>$shopId,'product_id'=>$productId]);
        respond(200, ['ok'=>true,'mode'=>'product_details','product'=>$product,'categories'=>$categories,'combinations'=>$combinations,'combinations_truncated'=>count($combinations)===200]);
    }

    if ($mode === 'stock_summary') {
        $defaultLow = int_param('low_stock_default', 5, 0, 10000);
        $summary = fetch_one($pdo, "
            SELECT COUNT(*) active_products,
                   SUM(COALESCE(sa.quantity,0)>0) products_in_stock,
                   SUM(COALESCE(sa.quantity,0)=0) products_zero_stock,
                   SUM(COALESCE(sa.quantity,0)<0) products_negative_stock,
                   SUM(COALESCE(sa.quantity,0)<=COALESCE(p.low_stock_threshold,{$defaultLow})) products_low_stock,
                   COALESCE(SUM(COALESCE(sa.quantity,0)),0) aggregate_available_units
            FROM `{$p}product` p
            LEFT JOIN `{$p}stock_available` sa ON sa.id_product=p.id_product AND sa.id_product_attribute=0 AND sa.id_shop=:shop
            WHERE p.id_shop_default=:shop2 AND p.active=1
        ", ['shop'=>$shopId,'shop2'=>$shopId]);
        $low = fetch_all($pdo, "
            SELECT p.id_product,p.reference,pl.name,COALESCE(sa.quantity,0) quantity,p.low_stock_threshold,
                   COALESCE(p.low_stock_threshold,{$defaultLow}) applied_threshold
            FROM `{$p}product` p
            LEFT JOIN `{$p}product_lang` pl ON pl.id_product=p.id_product AND pl.id_shop=:pl_shop AND pl.id_lang=:lang
            LEFT JOIN `{$p}stock_available` sa ON sa.id_product=p.id_product AND sa.id_product_attribute=0 AND sa.id_shop=:sa_shop
            WHERE p.id_shop_default=:shop AND p.active=1 AND COALESCE(sa.quantity,0)<=COALESCE(p.low_stock_threshold,{$defaultLow})
            ORDER BY COALESCE(sa.quantity,0) ASC,p.id_product LIMIT 100
        ", ['pl_shop'=>$shopId,'lang'=>$langId,'sa_shop'=>$shopId,'shop'=>$shopId]);
        respond(200, ['ok'=>true,'mode'=>'stock_summary','low_stock_default'=>$defaultLow,'summary'=>$summary,'lowest_stock_products'=>$low,'list_limit'=>100]);
    }

    if ($mode === 'product_quality_audit') {
        $activeOnly = int_param('active_only', 1, 0, 1);
        $limit = int_param('limit', 100, 1, 200);
        $activeClause = $activeOnly ? 'AND p.active=1' : '';

        // Keep each check simple and index-friendly. Duplicates are handled by
        // product_duplicates so this audit remains safe on a large catalogue.
        $core = fetch_one($pdo, "
            SELECT COUNT(*) audited_products,
                   SUM(TRIM(COALESCE(p.reference,''))='') missing_reference,
                   SUM(TRIM(COALESCE(p.ean13,''))='') missing_ean,
                   SUM(TRIM(COALESCE(p.ean13,''))<>'' AND (p.ean13 NOT REGEXP '^[0-9]+$' OR CHAR_LENGTH(p.ean13) NOT IN (8,13))) suspicious_ean,
                   SUM(p.id_manufacturer=0 OR p.id_manufacturer IS NULL) missing_manufacturer,
                   SUM(p.price<=0) non_positive_price
            FROM `{$p}product` p
            WHERE p.id_shop_default={$shopId} {$activeClause}
        ");
        $text = fetch_one($pdo, "
            SELECT SUM(TRIM(COALESCE(pl.name,''))='') missing_name,
                   SUM(CHAR_LENGTH(TRIM(COALESCE(pl.description,'')))<40) short_or_missing_description,
                   SUM(CHAR_LENGTH(TRIM(COALESCE(pl.description_short,'')))<20) short_or_missing_short_description,
                   SUM(TRIM(COALESCE(pl.meta_title,''))='') missing_meta_title,
                   SUM(TRIM(COALESCE(pl.meta_description,''))='') missing_meta_description
            FROM `{$p}product` p
            LEFT JOIN `{$p}product_lang` pl
              ON pl.id_product=p.id_product AND pl.id_shop={$shopId} AND pl.id_lang={$langId}
            WHERE p.id_shop_default={$shopId} {$activeClause}
        ");
        $stock = fetch_one($pdo, "
            SELECT SUM(p.active=1 AND COALESCE(sa.quantity,0)<=0) active_without_stock
            FROM `{$p}product` p
            LEFT JOIN `{$p}stock_available` sa
              ON sa.id_product=p.id_product AND sa.id_product_attribute=0 AND sa.id_shop={$shopId}
            WHERE p.id_shop_default={$shopId} {$activeClause}
        ");
        $images = fetch_one($pdo, "
            SELECT COUNT(*) missing_image
            FROM `{$p}product` p
            WHERE p.id_shop_default={$shopId} {$activeClause}
              AND NOT EXISTS (SELECT 1 FROM `{$p}image` i WHERE i.id_product=p.id_product)
        ");
        $summary = array_merge($core, $text, $stock, $images);

        $rows = fetch_all($pdo, "
            SELECT p.id_product,p.reference,p.ean13,p.active,p.price price_ex_tax,COALESCE(sa.quantity,0) stock_quantity,
                   pl.name,m.name manufacturer,COALESCE(img.image_count,0) image_count,
                   CONCAT_WS(',',
                     IF(TRIM(COALESCE(p.reference,''))='','missing_reference',NULL),
                     IF(TRIM(COALESCE(p.ean13,''))='','missing_ean',NULL),
                     IF(TRIM(COALESCE(p.ean13,''))<>'' AND (p.ean13 NOT REGEXP '^[0-9]+$' OR CHAR_LENGTH(p.ean13) NOT IN (8,13)),'suspicious_ean',NULL),
                     IF(p.id_manufacturer=0 OR p.id_manufacturer IS NULL,'missing_manufacturer',NULL),
                     IF(TRIM(COALESCE(pl.name,''))='','missing_name',NULL),
                     IF(CHAR_LENGTH(TRIM(COALESCE(pl.description,'')))<40,'short_or_missing_description',NULL),
                     IF(CHAR_LENGTH(TRIM(COALESCE(pl.description_short,'')))<20,'short_or_missing_short_description',NULL),
                     IF(TRIM(COALESCE(pl.meta_title,''))='','missing_meta_title',NULL),
                     IF(TRIM(COALESCE(pl.meta_description,''))='','missing_meta_description',NULL),
                     IF(p.price<=0,'non_positive_price',NULL),
                     IF(p.active=1 AND COALESCE(sa.quantity,0)<=0,'active_without_stock',NULL),
                     IF(img.id_product IS NULL,'missing_image',NULL)
                   ) issues
            FROM `{$p}product` p
            LEFT JOIN `{$p}product_lang` pl
              ON pl.id_product=p.id_product AND pl.id_shop={$shopId} AND pl.id_lang={$langId}
            LEFT JOIN `{$p}manufacturer` m ON m.id_manufacturer=p.id_manufacturer
            LEFT JOIN `{$p}stock_available` sa
              ON sa.id_product=p.id_product AND sa.id_product_attribute=0 AND sa.id_shop={$shopId}
            LEFT JOIN (
                SELECT id_product, COUNT(*) image_count FROM `{$p}image` GROUP BY id_product
            ) img ON img.id_product=p.id_product
            WHERE p.id_shop_default={$shopId} {$activeClause}
            HAVING issues<>''
            ORDER BY (issues LIKE '%non_positive_price%' OR issues LIKE '%missing_reference%') DESC,
                     (LENGTH(issues)-LENGTH(REPLACE(issues,',',''))+1) DESC,p.id_product
            LIMIT {$limit}
        ");
        respond(200, [
            'ok'=>true,'mode'=>'product_quality_audit','active_only'=>(bool)$activeOnly,
            'summary'=>$summary,'flagged_products'=>$rows,'list_limit'=>$limit,
            'duplicates_tool'=>'product_duplicates',
            'note'=>'Quality rules are review indicators; no product is modified. Duplicate identifiers are reported separately.'
        ]);
    }

    if ($mode === 'product_duplicates') {
        $limit = int_param('limit', 100, 1, 200);
        $productRefs = fetch_all($pdo, "
            SELECT reference identifier,COUNT(*) occurrences,
                   SUBSTRING_INDEX(GROUP_CONCAT(id_product ORDER BY id_product SEPARATOR ','),',',50) product_ids_sample
            FROM `{$p}product`
            WHERE id_shop_default={$shopId} AND TRIM(COALESCE(reference,''))<>''
            GROUP BY reference HAVING COUNT(*)>1
            ORDER BY occurrences DESC,identifier LIMIT {$limit}
        ");
        $productEans = fetch_all($pdo, "
            SELECT ean13 identifier,COUNT(*) occurrences,
                   SUBSTRING_INDEX(GROUP_CONCAT(id_product ORDER BY id_product SEPARATOR ','),',',50) product_ids_sample
            FROM `{$p}product`
            WHERE id_shop_default={$shopId} AND TRIM(COALESCE(ean13,''))<>''
            GROUP BY ean13 HAVING COUNT(*)>1
            ORDER BY occurrences DESC,identifier LIMIT {$limit}
        ");
        $slugs = fetch_all($pdo, "
            SELECT link_rewrite identifier,COUNT(*) occurrences,
                   SUBSTRING_INDEX(GROUP_CONCAT(id_product ORDER BY id_product SEPARATOR ','),',',50) product_ids_sample
            FROM `{$p}product_lang`
            WHERE id_shop={$shopId} AND id_lang={$langId} AND TRIM(COALESCE(link_rewrite,''))<>''
            GROUP BY link_rewrite HAVING COUNT(*)>1
            ORDER BY occurrences DESC,identifier LIMIT {$limit}
        ");
        $combinationRefs = fetch_all($pdo, "
            SELECT pa.reference identifier,COUNT(*) occurrences,
                   SUBSTRING_INDEX(GROUP_CONCAT(CONCAT(pa.id_product,':',pa.id_product_attribute) ORDER BY pa.id_product,pa.id_product_attribute SEPARATOR ','),',',50) combination_ids_sample
            FROM `{$p}product_attribute` pa
            JOIN `{$p}product` p0 ON p0.id_product=pa.id_product AND p0.id_shop_default={$shopId}
            WHERE TRIM(COALESCE(pa.reference,''))<>''
            GROUP BY pa.reference HAVING COUNT(*)>1
            ORDER BY occurrences DESC,identifier LIMIT {$limit}
        ");
        $combinationEans = fetch_all($pdo, "
            SELECT pa.ean13 identifier,COUNT(*) occurrences,
                   SUBSTRING_INDEX(GROUP_CONCAT(CONCAT(pa.id_product,':',pa.id_product_attribute) ORDER BY pa.id_product,pa.id_product_attribute SEPARATOR ','),',',50) combination_ids_sample
            FROM `{$p}product_attribute` pa
            JOIN `{$p}product` p0 ON p0.id_product=pa.id_product AND p0.id_shop_default={$shopId}
            WHERE TRIM(COALESCE(pa.ean13,''))<>''
            GROUP BY pa.ean13 HAVING COUNT(*)>1
            ORDER BY occurrences DESC,identifier LIMIT {$limit}
        ");
        respond(200, [
            'ok'=>true,'mode'=>'product_duplicates','limit_per_group'=>$limit,
            'product_references'=>$productRefs,'product_eans'=>$productEans,'slugs'=>$slugs,
            'combination_references'=>$combinationRefs,'combination_eans'=>$combinationEans,
            'note'=>'Blank identifiers are excluded. Results are read-only review candidates.'
        ]);
    }

    respond(400, ['ok'=>false,'error'=>'Unsupported mode']);

} catch (Throwable $e) {
    respond(500, ['ok'=>false,'error'=>'Bridge database operation failed','message'=>$e->getMessage(),'password_exposed'=>false]);
}
