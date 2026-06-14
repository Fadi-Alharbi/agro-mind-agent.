# 🗄️ خطة قاعدة البيانات — Agro-Mind Agent

> خطة كاملة لإدخال قاعدة بيانات علائقية (SQLite / MySQL) إلى المشروع،
> لتحلّ محلّ ملفات JSON المتناثرة والبيانات الوهمية (mock).

---

## 1. الوضع الحالي — وما المشكلة؟

| البيانات | أين تُخزَّن الآن | المشكلة |
|---|---|---|
| بروفايل العميل + المحادثات | ملفات JSON لكل جلسة في `memory/sessions/` | لا استعلام، لا ربط بين جلسات نفس العميل، تُقصّ على 20 رسالة |
| الطلبات | لا تُخزَّن إطلاقًا — `track_order()` يولّد حالة وهمية من رقم الطلب | لا يوجد طلب حقيقي، الحالة لا تتغير أبدًا |
| الاسترجاعات والفواتير | لا تُخزَّن — ردّ فوري ثم تُنسى | لا سجل، لا متابعة، لا تقارير |
| كتالوج المنتجات | ملف XLSX يُقرأ عند الإقلاع | بطيء، لا فهرسة، تعديل منتج = تعديل ملف Excel |
| سجل التصعيدات الأمنية | سطر في الـ log فقط | أخطر البيانات وأقلها تتبعًا! |

**الفائدة الجوهرية من قاعدة البيانات:**

1. **عميل واحد = هوية واحدة** عبر جلسات متعددة (اليوم كل جلسة "شخص جديد").
2. **طلبات حقيقية بدورة حياة**: إنشاء → شحن → تسليم → استرجاع.
3. **استعلامات وتقارير**: "كم تصعيدًا أمنيًا هذا الشهر؟"، "أكثر المنتجات ترشيحًا؟".
4. **تكامل البيانات**: قيود (Foreign Keys) تمنع طلبًا لمنتج غير موجود.
5. **التزامن**: ملفات JSON تنكسر إذا كتب طلبان في نفس اللحظة؛ قاعدة البيانات تتعامل مع هذا.

---

## 2. SQLite أم MySQL؟ — المقارنة

| المعيار | SQLite | MySQL |
|---|---|---|
| **التثبيت** | لا شيء — مدمج في بايثون (`sqlite3`) | خادم مستقل يجب تثبيته وإدارته |
| **التخزين** | ملف واحد `agro_mind.db` | خدمة + مجلدات نظام |
| **الكتابة المتزامنة** | كاتب واحد في اللحظة (يكفي لمئات المستخدمين مع WAL mode) | آلاف الكتابات المتزامنة |
| **عدّة خوادم تطبيق** | ❌ الملف محلي | ✅ خادم مركزي تتصل به عدة خدمات |
| **النسخ الاحتياطي** | نسخ ملف واحد | أدوات `mysqldump` وإدارة |
| **المستخدمون والصلاحيات** | لا يوجد | نظام صلاحيات كامل |
| **مناسب لـ** | نموذج أولي، عرض تقديمي، حتى ~100 ألف طلب | إنتاج فعلي متعدد الخوادم |

### ✅ القرار: SQLite الآن — عبر SQLAlchemy

**السبب:** المشروع نموذج أولي (frontend واحد + backend واحد على نفس الجهاز).
SQLite يعطينا كل فوائد SQL بصفر تكلفة تشغيلية. والأهم: باستخدام
**SQLAlchemy ORM** يصبح الانتقال إلى MySQL لاحقًا **تغيير سطر واحد**:

```python
# اليوم (تطوير):
DATABASE_URL = "sqlite:///db/agro_mind.db"

# غدًا (إنتاج) — نفس الكود تمامًا:
DATABASE_URL = "mysql+pymysql://user:pass@host:3306/agro_mind"
```

> 💡 **القاعدة:** لا تكتب SQL خامًّا مرتبطًا بمحرك معين. اكتب Models مرة
> واحدة، ودع SQLAlchemy يترجمها لأي محرك.

---

## 3. تصميم المخطط (Schema)

```
customers ──< sessions ──< messages
    │
    ├──< orders ──< refunds
    │       │
    │       └──> products (FK)
    │
    └──< escalations
products (من XLSX → جدول)
```

### الجداول

```sql
-- العملاء: الهوية الدائمة (بدل session_id المؤقت)
customers (
    id            INTEGER PK,
    external_id   TEXT UNIQUE,      -- معرف من تطبيق PDD أو الهاتف
    name          TEXT,
    location      TEXT,
    crop_type     TEXT,             -- آخر محصول معروف
    created_at    TIMESTAMP
)

-- الجلسات: محادثة واحدة مستمرة
sessions (
    id            TEXT PK,          -- UUID الحالي نفسه
    customer_id   INTEGER FK -> customers.id,
    last_intent   TEXT,
    started_at    TIMESTAMP,
    last_active   TIMESTAMP
)

-- الرسائل: كل دورة محادثة (بدل chat_history المقصوص)
messages (
    id            INTEGER PK,
    session_id    TEXT FK -> sessions.id,
    role          TEXT CHECK(role IN ('user','assistant')),
    content       TEXT,
    intent        TEXT,             -- النية المصنفة لهذه الرسالة
    has_image     BOOLEAN,
    created_at    TIMESTAMP
)

-- المنتجات: الكتالوج من XLSX إلى جدول
products (
    id            TEXT PK,          -- 'AF0001'
    name_en       TEXT, name_zh TEXT,
    category      TEXT, target_pest TEXT, crops TEXT,
    price_group   REAL, price_single REAL,
    active        BOOLEAN DEFAULT 1
)

-- الطلبات: دورة حياة حقيقية بدل المحاكاة
orders (
    id            TEXT PK,          -- 'ORD-2026-0001'
    customer_id   INTEGER FK -> customers.id,
    product_id    TEXT FK -> products.id,
    quantity      INTEGER,
    total_amount  REAL,
    is_group_buy  BOOLEAN,
    status        TEXT CHECK(status IN
                  ('pending','paid','packed','shipped',
                   'out_for_delivery','delivered','cancelled')),
    created_at    TIMESTAMP, updated_at TIMESTAMP
)

-- الاسترجاعات
refunds (
    id            INTEGER PK,
    order_id      TEXT FK -> orders.id,
    reason        TEXT,
    status        TEXT CHECK(status IN ('approved','under_review','rejected')),
    return_required BOOLEAN,
    created_at    TIMESTAMP
)

-- التصعيدات الأمنية: أهم جدول للتدقيق
escalations (
    id            INTEGER PK,
    session_id    TEXT FK -> sessions.id,
    risk_category TEXT,             -- self_harm / intentional_ingestion ...
    triggered_phrase TEXT,
    human_summary TEXT,
    resolved      BOOLEAN DEFAULT 0,
    created_at    TIMESTAMP
)
```

---

## 4. هيكل الكود الجديد

```
db/
├── __init__.py
├── engine.py        # إنشاء Engine + Session من DATABASE_URL
├── models.py        # كل جداول SQLAlchemy أعلاه
├── seed.py          # سكربت: XLSX → جدول products (يُشغَّل مرة)
└── repositories/
    ├── customers.py # get_or_create_customer, get_profile_context
    ├── orders.py    # create_order, track_order, update_status
    ├── messages.py  # append_turn, get_history
    └── escalations.py
```

> 💡 **نمط Repository:** الـ orchestrator لا يلمس SQLAlchemy مباشرة —
> يستدعي دوالًا باسم واضح (`track_order(order_id)`). هكذا نبدّل
> التخزين دون لمس منطق الوكيل.

---

## 5. خطة التنفيذ — 5 مراحل

### المرحلة 1: الأساس (يوم واحد)
- [ ] إضافة `sqlalchemy` إلى `requirements.txt`
- [ ] إنشاء `db/engine.py` (يقرأ `DATABASE_URL` من `.env`، الافتراضي SQLite)
- [ ] كتابة `db/models.py` بكل الجداول
- [ ] تفعيل WAL mode لـ SQLite (`PRAGMA journal_mode=WAL`) لتحسين التزامن
- [ ] إنشاء الجداول عند الإقلاع في `lifespan` بـ `main.py`

### المرحلة 2: المنتجات (نصف يوم)
- [ ] `db/seed.py`: قراءة `ProductCatalog_Translated_EN.xlsx` وإدخاله في جدول `products`
- [ ] تعديل `rag/catalog_loader.py` ليقرأ من الجدول بدل XLSX
  (مع إبقاء واجهة الدوال `search_catalog` / `get_product_by_id` كما هي —
  لا يتغير أي سطر في الـ orchestrator)

### المرحلة 3: الذاكرة والمحادثات (يوم واحد)
- [ ] إعادة كتابة `CustomerMemory` داخليًا فوق جدولي `sessions` + `messages`
  مع الحفاظ على نفس الواجهة (`append_turn`, `get_context_string`, `update`)
- [ ] ربط الجلسة بعميل: `get_or_create_customer(external_id)`
- [ ] سكربت هجرة اختياري: استيراد ملفات `memory/sessions/*.json` القديمة

### المرحلة 4: الطلبات الحقيقية (يوم واحد)
- [ ] `tools/agriculture_tools.py`:
  - `track_order()` → استعلام فعلي من جدول `orders`
  - `initiate_refund()` → إدراج صف في `refunds` + تحديث حالة الطلب
  - دالة جديدة `create_order()` تستدعيها الواجهة عند "Add to Cart"
- [ ] endpoint جديد في `main.py`: `POST /orders` + `GET /orders/{id}`
- [ ] ربط الوكيل بالأدوات عبر **OpenAI function calling**
  (الحلقة المفقودة حاليًا — النموذج "يؤلف" حالة الشحن بدل الاستعلام)

### المرحلة 5: التصعيدات والتقارير (نصف يوم)
- [ ] كل تصعيد أمني → صف في `escalations` (بدل سطر log يضيع)
- [ ] endpoint `GET /admin/escalations` لقائمة الحالات غير المحلولة
- [ ] اختبارات: `tests/test_db.py` (إنشاء طلب → تتبعه → استرجاعه)

---

## 6. متى ننتقل إلى MySQL؟

انتقلي **فقط** عند تحقق أحد هذه الشروط:

1. أكثر من خادم تطبيق واحد يحتاج نفس البيانات.
2. كتابات متزامنة كثيفة (مئات الطلبات/الدقيقة) تتجاوز قدرة كاتب SQLite الواحد.
3. حاجة لصلاحيات مستخدمين على مستوى قاعدة البيانات أو نسخ احتياطي مُدار.

**خطوات الانتقال حينها** (بفضل SQLAlchemy):
1. `pip install pymysql` وإنشاء قاعدة `agro_mind` على خادم MySQL.
2. تغيير `DATABASE_URL` في `.env`.
3. نقل البيانات: أداة مثل `sqlite3 .dump` + تحويل، أو سكربت بايثون يقرأ من القديم ويكتب في الجديد عبر نفس الـ Models.
4. إضافة Alembic لإدارة الهجرات (migrations) — مستحسن من المرحلة 1 أصلًا إن أردتِ الانضباط الكامل.

---

## 7. الخلاصة

| السؤال | الجواب |
|---|---|
| ماذا نستخدم؟ | **SQLite** عبر **SQLAlchemy ORM** |
| لماذا؟ | صفر إعداد، ملف واحد، يكفي النموذج الأولي تمامًا |
| الفائدة؟ | هوية عميل دائمة، طلبات حقيقية، سجل تصعيدات، تقارير، تكامل بيانات |
| ومتى MySQL؟ | عند التوسع لعدة خوادم أو كتابة متزامنة كثيفة — بتغيير سطر `DATABASE_URL` فقط |
| المدة المتوقعة؟ | ~4 أيام عمل على 5 مراحل |
