-- ════════════════════════════════════════════════════════════════════
-- Agro-Mind — استعلامات التحقق من قاعدة البيانات (Aiven MySQL)
-- شغّلها من لوحة Aiven Query Editor أو DBeaver أو mysql CLI.
-- ════════════════════════════════════════════════════════════════════

-- ── 1) هل أنا متصل بالقاعدة الصحيحة؟ ───────────────────────────────
SELECT DATABASE() AS current_db, VERSION() AS mysql_version;

-- ── 2) كل الجداول موجودة؟ (المتوقع: 8 جداول) ──────────────────────
SHOW TABLES;

-- ── 3) عدد الصفوف في كل جدول ──────────────────────────────────────
SELECT 'products'    AS table_name, COUNT(*) AS `rows` FROM products
UNION ALL SELECT 'customers',   COUNT(*) FROM customers
UNION ALL SELECT 'sessions',    COUNT(*) FROM sessions
UNION ALL SELECT 'messages',    COUNT(*) FROM messages
UNION ALL SELECT 'orders',      COUNT(*) FROM orders
UNION ALL SELECT 'refunds',     COUNT(*) FROM refunds
UNION ALL SELECT 'escalations', COUNT(*) FROM escalations
UNION ALL SELECT 'follow_ups',  COUNT(*) FROM follow_ups
UNION ALL SELECT 'diagnoses',   COUNT(*) FROM diagnoses
UNION ALL SELECT 'carts',       COUNT(*) FROM carts
UNION ALL SELECT 'cart_items',  COUNT(*) FROM cart_items;

-- ── 4) عيّنة من الكتالوج (المتوقع: 114 منتجًا) ─────────────────────
SELECT id, english_name, product_type, group_price, single_price
FROM products
LIMIT 10;

select * from escalations limit 10;

-- ── 5) هل النص الصيني سليم؟ (اختبار ترميز utf8mb4) ─────────────────
SELECT id, product_name, english_name
FROM products
WHERE product_name <> ''
LIMIT 5;

-- ── 6) فحص بنية جدول معيّن (الأعمدة وأنواعها) ─────────────────────
DESCRIBE products;
DESCRIBE orders;

-- ── 7) التحقق من المفاتيح الأجنبية (العلاقات بين الجداول) ──────────
SELECT
    TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = DATABASE()
  AND REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY TABLE_NAME;

-- ── 8) اختبار كتابة/قراءة سريع (أدخل ثم احذف صفًا تجريبيًا) ────────
-- INSERT INTO customers (name, location, crop_type) VALUES ('Test Farmer', 'Riyadh', 'tomato');
-- SELECT * FROM customers WHERE name = 'Test Farmer';
-- DELETE FROM customers WHERE name = 'Test Farmer';
