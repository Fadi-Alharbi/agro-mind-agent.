# 🚀 خطة الانتقال إلى Phase 2 — Agro-Mind Agentic

> خطة تنفيذ كاملة للانتقال من الكود الحالي (وكيل واحد، استدعاءات مباشرة)
> إلى المعمارية الموعودة في العرض المقدَّم للعميل عبر Beamdata:
> **وكيلان على LangGraph · RAG بـ Chroma · SQLite · بحث ويب · متابعة تلقائية · تقييم**.
>
> المرجع: `AgroMind Proposal - Client Meeting.pptx` (مايو 2026)
> وخطة قاعدة البيانات: [DATABASE_PLAN.md](DATABASE_PLAN.md)

---

## 0. أين نقف الآن؟ (تحليل الفجوة)

| القدرة الموعودة (شريحة) | الحالة | الفجوة |
|---|---|---|
| فحص أمان على كل رسالة + تصعيد (5) | ✅ منفّذ | تسجيل التصعيدات في DB فقط |
| واجهة محادثة واحدة (6) | ✅ منفّذ | ربط الصور بالتشخيص الجديد |
| ترجمة الكتالوج والمحادثات (9 — W1) | ✅ منفّذ | — |
| وكيلان على LangGraph (4) | ❌ | إعادة هيكلة الـ orchestrator |
| 8 أدوات حقيقية (4) | ⚠️ جزئي | تحويل المراحل إلى tools + أدوات جديدة |
| RAG بـ Chroma (4) | ❌ | فهرسة الكتالوج + المعرفة |
| SQLite (4) | ❌ | خطة DATABASE_PLAN جاهزة |
| بحث ويب fallback (3) | ❌ | أداة جديدة |
| ذاكرة عبر المحادثات + متابعة تلقائية (7) | ❌ | جدول customers + scheduler |
| رفض الصور خارج النطاق بثقة (9) | ⚠️ | confidence threshold |
| تقييم ~100 استعلام ضد خبير (8) | ❌ | dataset + إطار تقييم |

**المبدأ الحاكم للخطة:** كل أسبوع ينتهي بشيء قابل للعرض والاختبار،
ولا نكسر النظام العامل الحالي — نبني بجانبه ثم نبدّل.

---

## 1. المعمارية المستهدفة

```
                         ┌──────────────────────────────────────┐
 Farmer ── Streamlit ──> │ FastAPI /chat                        │
                         │   │                                  │
                         │   ▼                                  │
                         │ SafetyInterceptor (كل رسالة)         │
                         │   │ آمنة                              │
                         │   ▼                                  │
                         │ ╔════════════════════╗               │
                         │ ║  Support Agent     ║  LangGraph    │
                         │ ║  (يدير المحادثة)   ║               │
                         │ ╚════════════════════╝               │
                         │   tools:                             │
                         │   • retrieve_kb        → Chroma      │
                         │   • recommend_product  → Chroma+SQL  │
                         │   • lookup_order       → SQLite      │
                         │   • escalate_human     → SQLite      │
                         │   • web_search         → Tavily/DDG  │
                         │   │ صورة / حالة مرض                  │
                         │   ▼ delegates                        │
                         │ ╔════════════════════╗               │
                         │ ║  Diagnosis Agent   ║               │
                         │ ╚════════════════════╝               │
                         │   • vision_analyze (+ refusal)       │
                         │   • disease_kb         → Chroma      │
                         │   • web_search                       │
                         └──────────┬───────────────────────────┘
                                    │
              SQLite ◄──────────────┤  (profiles, orders, escalations,
              Chroma ◄──────────────┘   messages, follow_ups)
                                    
              Scheduler (APScheduler) ──> متابعة بعد 3-7 أيام حسب المنتج
```

**ملاحظات تصميمية:**
- `SafetyInterceptor` يبقى **خارج** الـ graph وقبله — حتمي ولا يعتمد على LLM (كما هو اليوم، وهذا صحيح معماريًا).
- `classify_intent` يصبح ضمنيًا: الـ Support Agent يقرر بنفسه أي أداة يستدعي (هذا جوهر "agentic" في شريحة 3 — لا شجرة قواعد).
- الـ Diagnosis Agent يُستدعى كـ **subgraph/tool** من الـ Support Agent ويعيد تشخيصًا منظمًا (structured).

---

## 2. خطة الأسابيع (W2 → W5 من جدول المقترح)

> W1 (البيانات والترجمة) منجز فعليًا. الخطة أدناه تغطي ما تبقى،
> مرتبة بحيث تُبنى التبعيات أولًا: **DB → RAG → Agents → Vision/Follow-up → Eval**.

### 🔹 الأسبوع A — الأساسات: SQLite + Chroma RAG

**الهدف:** بنية بيانات حقيقية تحتها كل ما يأتي لاحقًا.

| # | المهمة | الملفات | التفاصيل |
|---|---|---|---|
| A1 | تنفيذ المراحل 1+2 من [DATABASE_PLAN.md](DATABASE_PLAN.md) | `db/engine.py`, `db/models.py`, `db/seed.py` | SQLAlchemy + الجداول السبعة + ترحيل الكتالوج من XLSX |
| A2 | جدول إضافي `follow_ups` | `db/models.py` | `(id, customer_id, order_id, product_id, due_at, status, result_note)` — أساس شريحة 7 |
| A3 | إنشاء فهرس Chroma | `rag/vectorstore.py` | تضمين (embed) الكتالوج الـ 77 منتجًا + محادثات `tra/` المترجمة كقاعدة معرفة أمراض |
| A4 | أداة `retrieve_kb` | `rag/vectorstore.py` | بحث دلالي top-k مع مصدر كل نتيجة (للـ faithfulness لاحقًا) |
| A5 | إبقاء التوافق | `rag/catalog_loader.py` | نفس واجهة `search_catalog` تقرأ من SQLite — النظام القديم يستمر بالعمل |

**مخرج الأسبوع:** `pytest tests/test_db.py tests/test_rag.py` أخضر +
استعلام دلالي يعيد منتجات صحيحة بمصادرها.

---

### 🔹 الأسبوع B — الوكيلان على LangGraph

**الهدف:** استبدال خط الأنابيب الثابت بوكيل يقرر بنفسه.

| # | المهمة | الملفات | التفاصيل |
|---|---|---|---|
| B1 | إضافة `langgraph`, `langchain`, `langchain-openai` | `requirements.txt` | تثبيت الإصدارات وتجميدها |
| B2 | تعريف الأدوات الثماني كـ `@tool` | `tools/agent_tools.py` (جديد) | تغليف: `retrieve_kb`, `recommend_product`, `lookup_order` (يقرأ SQLite فعليًا), `escalate_human` (يكتب صف escalation), `web_search`, `vision_analyze`, `disease_kb` |
| B3 | بناء Support Agent | `agent/support_agent.py` | LangGraph ReAct agent + system prompt من `prompts.py` + ذاكرة من DB |
| B4 | بناء Diagnosis Agent | `agent/diagnosis_agent.py` | يستقبل صورة + سياق، يعيد `{disease, confidence, off_topic, treatment, sources}` منظمًا |
| B5 | ربط التفويض (delegation) | `agent/graph.py` | الـ Support Agent يستدعي الـ Diagnosis Agent كأداة عند صورة/مرض |
| B6 | أداة `web_search` | `tools/agent_tools.py` | Tavily (مفتاح API) أو DuckDuckGo كبديل مجاني — fallback عندما يعيد `retrieve_kb` نتائج ضعيفة |
| B7 | التبديل خلف flag | `main.py` | `AGENT_MODE=langgraph|legacy` في `.env` — العرض القديم يبقى احتياطيًا |

**مخرج الأسبوع:** محادثة كاملة end-to-end عبر LangGraph:
سؤال نصي → `retrieve_kb` → إجابة مع مصدر، وسؤال طلب → `lookup_order` → حالة من SQLite.

---

### 🔹 الأسبوع C — الرؤية، الذاكرة الدائمة، والمتابعة التلقائية

**الهدف:** الميزات التي تميّز العرض: رفض الصور خارج النطاق + "كيف سار العلاج؟".

| # | المهمة | الملفات | التفاصيل |
|---|---|---|---|
| C1 | رفض الصور خارج النطاق | `agent/diagnosis_agent.py` | البرومبت يطلب `off_topic` + `confidence`؛ تحت العتبة (مثلًا 0.6) → رد مهذب أو تصعيد (يطابق `_zero_guess_response` الحالي) |
| C2 | هوية عميل دائمة | `db/repositories/customers.py`, `frontend/app.py` | حقل اختياري في الواجهة (هاتف/معرف) → `get_or_create_customer`؛ الجلسات الجديدة تُربط به |
| C3 | بروفايل عبر المحادثات | `memory/customer_memory.py` | `get_context_string` يقرأ من DB: المحصول، الموقع، آخر التشخيصات، آخر المشتريات — عبر **كل** الجلسات |
| C4 | إنشاء متابعة عند الشراء/الترشيح | `tools/agent_tools.py` | عند `recommend_product`/إنشاء طلب → صف في `follow_ups` بـ `due_at` حسب نوع المنتج (مبيد سريع = 3 أيام، جهازي = 7) |
| C5 | المجدول | `scheduler/follow_up.py` (جديد) | APScheduler داخل lifespan في `main.py`: كل ساعة يلتقط المتابعات المستحقة → يولّد رسالة "كيف سار العلاج؟" → يضيفها لمحادثة العميل (وفي الواجهة: إشعار عند فتح الجلسة) |
| C6 | تسجيل التصعيدات + لوحة بسيطة | `main.py` | كل تصعيد → جدول `escalations` + endpoint `GET /admin/escalations` |

**مخرج الأسبوع:** سيناريو العرض الحي لشريحة 7 يعمل:
شراء → متابعة مجدولة → (بتسريع المؤقت) رسالة متابعة تظهر → الرد يُسجَّل في البروفايل.

---

### 🔹 الأسبوع D — التقييم (Evaluation)

**الهدف:** الالتزام الصريح في شريحة 8: ~100 استعلام، 5 مقاييس، Human vs Agent.

| # | المهمة | الملفات | التفاصيل |
|---|---|---|---|
| D1 | بناء dataset التقييم | `evaluation/dataset.jsonl` | ~100 حالة من 4 فئات: Q&A نصية (من `tra/fine_tuning`) · صور محاصيل + صور off-topic · حالات تصعيد (من `cat4`) · حالات regional edge — لكل حالة إجابة مرجعية من خبير |
| D2 | اختيار الإطار وتثبيته | `evaluation/run_eval.py` | **التوصية: RAGAS** للـ faithfulness/answer accuracy + **سكربت مخصص** لـ tool-selection وsafety (أبسط من DeepEval لحالتنا)؛ LangSmith اختياري للتتبع |
| D3 | المقاييس الخمسة | `evaluation/metrics.py` | ① answer accuracy ② faithfulness (مرتبط بمصادر `retrieve_kb`) ③ tool-selection accuracy (من trace الـ graph) ④ image diagnosis quality (صحة المرض + رفض off-topic) ⑤ safety escalation recall — **هذا المقياس يجب أن يكون 100%** |
| D4 | تشغيل أولي + إصلاح | — | تشغيل كامل → تحليل الإخفاقات → ضبط البرومبتات والـ retrieval (top-k، حجم المقاطع) → إعادة تشغيل |
| D5 | تقرير النتائج | `evaluation/REPORT.md` | جدول Human vs Agent لكل مقياس — وهو ما ستقدمه Beamdata للعميل |

**مخرج الأسبوع:** تقرير أرقام فعلي قابل للتسليم.

---

### 🔹 الأسبوع E — الصقل والعرض النهائي

| # | المهمة | التفاصيل |
|---|---|---|
| E1 | حالات الحافة | رسائل فارغة، صور ضخمة/تالفة، انقطاع OpenAI (رسالة لائقة بدل stack trace)، خلط لغات |
| E2 | تنظيف التناقضات | إزالة بقايا Gemini من `/health` في `main.py` · حذف المسار القديم بعد ثبات LangGraph · تحديث README بالمعمارية الجديدة |
| E3 | سيناريو الديمو | سكربت عرض يطابق الشرائح 5-7: صورة طماطم → تشخيص → ترشيح Mancozeb → شراء → متابعة → سؤال أمان → تصعيد |
| E4 | dry-run كامل | بروفة العرض مرتين + خطة بديلة (تسجيل فيديو احتياطي) |

---

## 3. ترتيب الأولويات إذا ضاق الوقت

ليس كل البنود متساوية أمام العميل. إن اضطررتم للتضحية:

| أولوية | البند | لماذا |
|---|---|---|
| 🟥 لا يُمس | Safety escalation 100% + تسجيلها | وعد أخلاقي وتعاقدي، وأسهل ما يُختبر |
| 🟥 لا يُمس | LangGraph بوكيلين + الأدوات | هو **تعريف** Phase 2 في العرض — بدونه لا يوجد مشروع |
| 🟧 مهم جدًا | RAG بـ Chroma + faithfulness | أساس مقياسين من خمسة في التقييم |
| 🟧 مهم جدًا | المتابعة التلقائية | أقوى لحظة "wow" في العرض (شريحة 7) — حتى لو بمؤقت مسرَّع للديمو |
| 🟨 قابل للتبسيط | web_search | يمكن أن يكون DuckDuckGo بسيطًا بدل Tavily |
| 🟨 قابل للتبسيط | لوحة admin | endpoint JSON يكفي، لا حاجة لواجهة |
| 🟩 خارج النطاق (شريحة 9 صراحةً) | حسابات، checkout حقيقي، logistics API، fine-tuning للرؤية، scaling | العرض استثناها بنفسه — لا تنجرّوا إليها |

---

## 4. المخاطر وخطط التخفيف

| الخطر | الاحتمال | التخفيف |
|---|---|---|
| ضعف retrieval بسبب الترجمة (ذكره العرض نفسه) | متوسط | فحص عينة في بداية الأسبوع A؛ البديل: نموذج تضمين متعدد اللغات (`text-embedding-3-large` يدعم الصينية والإنجليزية) والفهرسة بالنصين معًا |
| الرؤية تشخّص صور off-topic (ذكره العرض) | متوسط | `off_topic` flag + عتبة ثقة + حالات off-topic في dataset التقييم تقيسها فعليًا |
| منحنى تعلم LangGraph يأكل الأسبوع B | متوسط | البدء بـ `create_react_agent` الجاهز بدل graph مخصص؛ التعقيد لاحقًا |
| تكلفة/بطء gpt-4o في التقييم (100 حالة × أدوات) | منخفض | تشغيل التقييم بدفعات + كاش للردود + نموذج أرخص للحالات النصية البسيطة |
| المتابعة التلقائية بلا قناة إرسال حقيقية (لا إشعارات push) | مؤكد | للديمو: الرسالة تظهر عند فتح الجلسة + عرض جدول `follow_ups`؛ القناة الفعلية (PDD API) خارج النطاق المعلن |

---

## 5. تعريف "تمّ" (Definition of Done)

- [ ] محادثة كاملة تمر عبر Support Agent على LangGraph (لا مسار legacy في الديمو)
- [ ] صورة مرض → Diagnosis Agent → تشخيص منظم بمصادر؛ صورة قطة → رفض مهذب
- [ ] سؤال طلب → حالة حقيقية من جدول `orders` في SQLite
- [ ] سؤال خارج قاعدة المعرفة → `web_search` يُستدعى ويُذكر المصدر
- [ ] عميل عائد يُعرَف باسمه ومحصوله من جلسة سابقة
- [ ] متابعة مجدولة تُطلق رسالة "كيف سار العلاج؟" تلقائيًا
- [ ] رسالة خطرة → تصعيد فوري + صف في `escalations` (recall = 100% على dataset الأمان)
- [ ] تقرير تقييم: 5 مقاييس × ~100 حالة، Human vs Agent
- [ ] README محدَّث + سيناريو ديمو مكتوب ومُجرَّب مرتين

---

## 6. أول ثلاث خطوات عملية (ابدئي هنا)

1. **اليوم:** تثبيت الحزم — `sqlalchemy chromadb langgraph langchain langchain-openai apscheduler ragas` وتجميد `requirements.txt`.
2. **A1:** إنشاء `db/models.py` بالجداول الثمانية (السبعة في DATABASE_PLAN + `follow_ups`) وتشغيل `db/seed.py` لترحيل الكتالوج.
3. **A3:** سكربت فهرسة Chroma للكتالوج + اختبار: «sticky trap for whiteflies» يعيد المنتج الصحيح دلاليًا حيث يفشل بحث الكلمات المفتاحية.
