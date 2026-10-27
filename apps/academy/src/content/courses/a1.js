// Course A1 — Introduction to Artificial Intelligence in Agriculture.
// Complete instruction, module quizzes and a certification question bank.
// Status is "review": it appears as upcoming until an administrator reviews and
// publishes it. Each lesson carries a spoken script for its planned video.

export const A1 = {
  id: "crs_a1",
  status: "review",
  planned_release_date: "2026-10-29",
  content_review_note: "Faculty review of lesson text and exam bank before publication; record Joshua videos from the attached scripts once approved.",
  description: `Artificial intelligence is arriving in agriculture through irrigation controllers, satellite services, farm management software and the phones in growers' pockets. This course gives you a clear, practical understanding of what that technology is, how it works, and how to use it well.

You will learn the core ideas behind AI and machine learning without equations, see how agricultural data becomes a prediction and then a recommendation, and follow AI through the season — from planning and irrigation to crop health and harvest. Above all, you will learn to judge AI output: when to trust it, when to question it, and how to keep human judgment and farm knowledge in charge.

The course is designed for growers, operators, agronomists, managers and students. No technical background is required.`,
  objectives: [
    "Explain in plain language what artificial intelligence, machine learning and generative AI are",
    "Describe the main sources of agricultural data and what makes data trustworthy",
    "Follow how a model turns data into a prediction and a prediction into a recommendation",
    "Recognize practical AI applications across the crop season, from planning to harvest",
    "Identify the limits and failure modes of agricultural AI and when to challenge a recommendation",
    "Apply principles of data ownership, privacy and responsible use on your own operation",
  ],
  prerequisites_text: "None. Curiosity about how technology can support agricultural work is all you need.",
  modules: [
    {
      id: "mod_a1_1",
      title: "What AI means for agriculture",
      summary: "Core ideas and why they matter now.",
      lessons: [
        {
          id: "les_a1_welcome",
          slug: "welcome",
          title: "Welcome to the course",
          type: "text",
          minutes: 5,
          preview: true,
          summary: "What you will learn, how the course works, and how to earn your certificate.",
          body: `Welcome to **Introduction to Artificial Intelligence in Agriculture**, the first course of the AGRO-AI Academy *Foundations of Agricultural AI* program.

You do not need any technical background to succeed here. If you have ever looked at a weather forecast, read a soil test or compared yields between two fields, you already use the habits of mind that this course builds on: collecting evidence, spotting patterns and deciding what to do next.

## What you will learn

By the end of the course you will be able to:

- explain what AI is — and is not — in plain language;
- describe where agricultural data comes from and what makes it reliable;
- follow how data becomes a prediction, and a prediction becomes a recommendation;
- recognize useful AI applications across the season;
- judge AI output critically and use it responsibly.

## How the course works

The course has **four modules**. Each module contains short lessons and ends with a quiz that helps you check your understanding. Quizzes do not count toward your certificate, and you can retake them as often as you like.

Your progress is saved automatically. You can stop in the middle of a lesson on your phone and continue later on a computer.

> **Tip:** Use the **Notes** tab under each lesson to write down ideas that apply to your own operation. Notes are private — only you can see them.

## Earning your certificate

When you have completed every required lesson, the **final exam** unlocks. It draws 20 questions from a larger bank, is timed at 30 minutes, and requires a score of **80%** to pass. If you do not pass on the first try, you can review the recommended lessons and try again after one hour.

Pass the exam and AGRO-AI Academy issues your certificate automatically — free, with a unique credential ID and a public verification page you can share on LinkedIn.

Let's begin.`,
          script: `Hello, and welcome to AGRO-AI Academy. I'm Joshua, and I'll be your guide through Introduction to Artificial Intelligence in Agriculture.

You don't need a technical background for this course. If you've ever compared two fields, read a soil test, or checked the forecast before irrigating, you already think the way good AI systems are designed to work: gather evidence, find patterns, decide what to do.

Over four short modules, we'll cover what AI really is, how farm data becomes a recommendation, where AI helps across the season, and — just as important — where it can go wrong.

Your progress saves automatically, so learn a few minutes at a time. Each module ends with a practice quiz. When you finish the lessons, the final exam unlocks. Score eighty percent and you'll receive a free, verifiable certificate.

Let's get started.`,
        },
        {
          id: "les_a1_what_is_ai",
          slug: "what-ai-is",
          title: "From rules to learning: what AI is (and isn't)",
          type: "text",
          minutes: 12,
          preview: true,
          summary: "Plain-language definitions of AI, machine learning, deep learning and generative AI.",
          body: `"Artificial intelligence" is used to describe everything from a simple sensor alarm to a chatbot that writes essays. Before we look at agriculture, we need clear words.

## Artificial intelligence

**Artificial intelligence (AI)** is the broad field of building computer systems that perform tasks we normally associate with human intelligence: recognizing patterns, making predictions, understanding language and choosing actions.

That definition is wide on purpose. It includes very different technologies, so it helps to separate two ways of building them.

## Rules versus learning

**Rule-based systems** follow instructions written by people. An irrigation controller that says *"if soil moisture falls below 25%, start the pump"* is following a rule. Rules are transparent and predictable, but someone has to know the right rule in advance, and rules do not adapt when conditions change.

**Machine learning (ML)** systems learn patterns from examples instead. Show a model thousands of past seasons — weather, soil, irrigation and the yields that followed — and it can learn relationships that no one wrote down explicitly. Most of what people call "AI" today is machine learning.

| | Rule-based system | Machine learning model |
|---|---|---|
| Where the logic comes from | People write it | Learned from data |
| Strength | Transparent, predictable | Finds complex patterns, adapts with new data |
| Weakness | Rigid; misses what designers didn't foresee | Only as good as its data; can be hard to explain |
| Farm example | Pump starts below a moisture threshold | Model predicts tomorrow's crop water use |

## Deep learning

**Deep learning** is a family of machine learning methods built from many-layered "neural networks". It is especially good at messy, high-dimensional data such as images and sound. When a phone app recognizes a leaf disease from a photo, deep learning is usually behind it.

## Generative AI

**Generative AI** creates new content — text, images, audio or code — based on patterns learned from very large datasets. Large language models (LLMs), the technology behind conversational assistants, are generative AI. They can explain concepts, summarize reports and answer questions in many languages.

Generative AI is powerful, but it predicts *plausible* words, not verified facts. It can state something false with complete confidence. In agriculture, a generative assistant is useful for explaining and drafting, but important numbers and decisions must be checked against trusted data.

> **Key idea:** AI is not one machine. It is a toolbox. Rules, statistical models, deep learning and generative models each fit different problems.

## What AI is not

- **AI is not magic.** Every output comes from data and design choices made by people.
- **AI does not "understand" your farm** the way you do. It knows only what its data captured.
- **AI is not automatically right.** Predictions carry uncertainty, and the best systems tell you how much.
- **AI does not replace judgment.** It is a decision-support tool. Responsibility for the decision stays with people.

## Check your understanding

Think of a tool you already use — a weather app, a yield monitor, a spreadsheet with formulas. Is its logic written as rules, or learned from data? Write your answer in your notes; we will return to this idea in Module 2.`,
          script: `"Artificial intelligence" gets used for almost everything, so let's be precise.

AI is the broad field of building systems that do tasks we associate with human intelligence — recognizing patterns, predicting, understanding language.

There are two big ways to build them. Rule-based systems follow instructions people write: if soil moisture drops below twenty-five percent, start the pump. Clear and predictable — but rigid.

Machine learning learns patterns from examples instead. Show a model many seasons of weather, soil, irrigation and yield, and it can learn relationships nobody wrote down.

Deep learning is a powerful branch of machine learning that excels at images and sound — like recognizing leaf disease in a photo. Generative AI creates new text or images. It's great for explaining and drafting, but it predicts plausible words, not verified facts.

Remember: AI is a toolbox, not magic. And the decision is always yours.`,
        },
        {
          id: "les_a1_why_now",
          slug: "why-agriculture-needs-ai",
          title: "Why agriculture is turning to AI now",
          type: "text",
          minutes: 10,
          summary: "The pressures and opportunities driving AI adoption on farms.",
          body: `Farmers have always used information to make decisions. What has changed is the amount of information available, the speed at which it must be used, and the pressure on every resource.

## Pressures on the modern farm

**Water.** Agriculture is the largest user of fresh water worldwide; according to the UN Food and Agriculture Organization, irrigated agriculture accounts for roughly 70% of global freshwater withdrawals. In many regions, water allocations are shrinking while demand grows. Every irrigation decision matters.

**Climate variability.** Seasons are less predictable. Heat waves, irregular rainfall and new pest pressures make last year's playbook less reliable.

**Costs and margins.** Fertilizer, energy, labor and equipment costs can swing sharply. Applying the right amount in the right place protects both the margin and the environment.

**Labor.** Many operations struggle to find and retain skilled people. Knowledge that lives in one experienced manager's head is at risk when that person is unavailable.

**Expectations from buyers and regulators.** Supply chains increasingly ask for evidence: how much water was used, which inputs were applied, what practices were followed.

## Why AI, and why now

Three things came together:

1. **Data became abundant.** Satellites now revisit most farmland every few days. Soil moisture probes, weather stations, irrigation controllers and machinery all produce continuous data.
2. **Computing became cheap and connected.** Models that once needed a research lab can run in the cloud and deliver results to a phone.
3. **Methods matured.** Machine learning, computer vision and language models have improved rapidly and are now practical tools.

> **Key idea:** AI does not create new resources. It helps you make better use of the water, inputs, time and knowledge you already have.

## What AI can realistically do

- **Sense** — turn raw imagery and sensor data into information, such as which zones of a field are stressed.
- **Predict** — estimate what will happen, such as tomorrow's crop water demand or end-of-season yield.
- **Recommend** — suggest an action, such as an irrigation schedule, and explain why.
- **Verify** — check whether an action happened and whether it worked.

Notice the pattern: sense, predict, recommend, verify. We will use this loop throughout the course.

## What it cannot do

AI cannot see what its data does not capture: a broken valve, a neighbor's spraying, a cultural practice unique to your farm. It cannot carry responsibility for a decision. And it cannot replace the trust between a grower and an advisor. Good agricultural AI is designed to work *with* people who know the land.`,
          script: `Why is agriculture turning to AI now?

Start with the pressures. Irrigated agriculture accounts for roughly seventy percent of global freshwater withdrawals, and allocations are tightening. Seasons are less predictable. Input costs swing. Skilled labor is hard to find. And buyers increasingly want evidence of how food was produced.

At the same time, three things changed. Data became abundant — satellites, probes, weather stations and machines report constantly. Computing became cheap and connected. And the methods matured.

AI doesn't create more water or more fertilizer. It helps you use what you have more precisely.

Keep this simple loop in mind: sense, predict, recommend, verify. We'll use it all course long.

And remember what AI can't do: it can't see what its data misses, and it can't carry responsibility. That stays with you.`,
        },
        {
          id: "les_a1_quiz1",
          slug: "module-1-quiz",
          title: "Module 1 quiz",
          type: "quiz",
          minutes: 8,
          assessment: "asm_a1_q1",
          summary: "Check your understanding of AI fundamentals.",
          body: "Answer five quick questions about the ideas in Module 1. Quizzes are for practice: you can retake them as many times as you like, and you'll see explanations after each attempt.",
        },
      ],
    },
    {
      id: "mod_a1_2",
      title: "How agricultural AI works",
      summary: "From data to model to recommendation.",
      lessons: [
        {
          id: "les_a1_data",
          slug: "data-the-raw-material",
          title: "Data: the raw material of agricultural AI",
          type: "text",
          minutes: 14,
          summary: "Where farm data comes from and what makes it trustworthy.",
          body: `Every AI system is built from data. If the data is incomplete, biased or wrong, the AI will be too. Understanding your data is the most important skill in agricultural AI.

## Where agricultural data comes from

| Source | Examples | What it tells you |
|---|---|---|
| Weather | On-farm stations, regional networks, forecasts | Temperature, rainfall, humidity, wind, solar radiation |
| Soil | Moisture probes, soil tests, soil maps | Water available to roots, nutrients, texture |
| Remote sensing | Satellite, aircraft and drone imagery | Crop vigor, canopy cover, stress patterns across a field |
| Equipment | Irrigation controllers, flow meters, yield monitors, tractors | What was applied, where and when |
| Records | Planting dates, varieties, input applications, scouting notes | Management decisions and observations |
| Markets | Prices, contracts, demand signals | Economic context for decisions |

## The qualities of good data

**Accuracy** — does the measurement reflect reality? A moisture probe installed in a wet spot, or a rain gauge under a tree, will mislead every model that uses it.

**Completeness** — are there gaps? A sensor that stops reporting for a week during a heat wave leaves a hole exactly when it matters most.

**Timeliness** — is the data recent enough for the decision? Yesterday's soil moisture is useful for today's irrigation; last month's is not.

**Consistency** — are units, formats and definitions the same over time and across fields? Mixing inches and millimeters, or two names for the same field, causes silent errors.

**Representativeness** — does the data cover the conditions where the AI will be used? A model trained only on sandy soils may not work on clay.

> **Field check:** Before trusting a dashboard, ask three questions: Where did this number come from? When was it measured? What would make it wrong?

## Data needs context

A soil moisture reading of 30% means little on its own. It matters what the soil type is, how deep the sensor sits, which crop is growing and at what stage. Good agricultural AI combines data sources so that each one adds context to the others — for example, pairing satellite imagery with weather data and the field's irrigation history.

## Your data, your decisions

Farm data has value — commercial, operational and personal. Before connecting equipment or sharing records with any service, understand who can access the data, how it will be used, and whether you can take it with you if you leave. We will return to data ownership in Module 4.`,
          script: `Every AI system is built from data — and it inherits every flaw in that data.

On a farm, data comes from weather stations, soil probes, satellite and drone imagery, controllers and flow meters, yield monitors, your own records, and market prices.

Good data has five qualities. It's accurate — a rain gauge under a tree will mislead you. It's complete — gaps during a heat wave hurt most. It's timely. It's consistent in units and names. And it's representative of the conditions where the AI will be used.

Here's a habit worth building. Before you trust any number on a dashboard, ask: where did it come from, when was it measured, and what could make it wrong?

And remember: farm data has value. Know who can access yours and how it's used.`,
        },
        {
          id: "les_a1_models",
          slug: "models-training-and-predictions",
          title: "Models, training and predictions",
          type: "text",
          minutes: 14,
          summary: "How a model learns from examples and why every prediction has uncertainty.",
          body: `A **model** is a mathematical description of a relationship — for example, between weather and the amount of water a crop uses. Machine learning builds models by learning from examples.

## Learning from examples

Imagine you want to predict how much water an almond orchard will use tomorrow. You collect many past days, each with:

- the **inputs** (also called *features*): temperature, humidity, wind, solar radiation, tree age, canopy cover;
- the **outcome** you want to predict: the water the orchard actually used that day, measured by sensors.

During **training**, the algorithm adjusts the model again and again until its predictions match the recorded outcomes as closely as possible. This is called **supervised learning**, because every example comes with the correct answer.

## Testing on data the model has never seen

A model can memorize its training examples and still fail on new days. That is why data scientists keep some data aside for **validation** — data the model never saw during training. Performance on that held-out data is the honest measure of how well it works.

> **Important:** Ask how a model was validated. "It fit our historical data perfectly" is a warning sign, not a strength.

## Measuring accuracy

For numerical predictions, common measures include the **average error** (how far off predictions are, on average) and how much of the variation the model explains. For classifications — "stressed" or "healthy" — we ask how often the model is right, and how often it raises false alarms or misses real problems.

There is no single "good" accuracy. A yield forecast that is within 5% may be excellent for marketing decisions; a frost alarm that misses one event in ten may be unacceptable.

## Every prediction has uncertainty

Weather changes, sensors drift and fields vary. A trustworthy system communicates uncertainty: "tomorrow's water use is 6.2 mm, likely between 5.6 and 6.8 mm." A single number with no range hides important information.

## When models go stale

Conditions change. New varieties, a drought year or a changed irrigation system can make past data less representative. This is called **drift**. Good systems monitor their own accuracy over time and are retrained when performance drops.

## Common types of agricultural models

- **Regression** — predicts a number (water use, yield, price).
- **Classification** — assigns a category (disease present or absent, crop type).
- **Forecasting** — predicts how something will change over time (soil moisture over the next five days).
- **Computer vision** — interprets images (counting fruit, detecting weeds).
- **Optimization** — finds the best plan within constraints (an irrigation schedule that meets crop demand with limited water).`,
          script: `A model is a mathematical description of a relationship — say, between weather and how much water an orchard uses.

Machine learning builds that model from examples. Each past day has inputs — temperature, humidity, wind, sunlight, canopy — and an outcome: the water actually used. Training adjusts the model until its predictions match those outcomes.

But fitting the past isn't the goal. Good teams hold back data the model never saw and test on it. That's the honest measure. If someone tells you a model fit their history perfectly, be cautious.

Every prediction carries uncertainty. A trustworthy system says, "about six point two millimeters, likely between five point six and six point eight." And conditions change, so models can drift and need monitoring and retraining.

You'll meet regression, classification, forecasting, computer vision and optimization. Different tools, same principle: learn from evidence, then prove it on new data.`,
        },
        {
          id: "les_a1_recommendations",
          slug: "from-prediction-to-recommendation",
          title: "From prediction to recommendation",
          type: "text",
          minutes: 12,
          summary: "How decision-support systems turn predictions into actions — and keep people in the loop.",
          body: `A prediction tells you what is likely to happen. A **recommendation** tells you what to do about it. Turning one into the other requires goals, constraints and context.

## An irrigation example

Suppose a model predicts that a field will use 7 mm of water tomorrow and that soil moisture is already near the lower limit the crop tolerates. A recommendation system combines that prediction with:

- **goals** — protect yield and quality, avoid waste;
- **constraints** — the pump capacity, the water allocation remaining, electricity tariffs, the irrigation set schedule;
- **context** — forecast rain, crop stage, a planned harvest that needs dry ground.

The result might be: *"Irrigate block 4 tonight for 6 hours (about 18 mm). Skip block 7: 12 mm of rain is forecast with high confidence."*

## Good recommendations explain themselves

A recommendation you cannot understand is a recommendation you cannot judge. Look for systems that show:

- **the reason** — which data and which prediction drove the suggestion;
- **the confidence** — how certain the system is;
- **the alternatives** — what happens if you wait, or apply less;
- **the evidence trail** — so you can check afterward whether the action happened and worked.

## Keeping people in the loop

In agriculture, most AI is **decision support**: the system proposes, a person decides. Even where automation executes actions — for example, a controller opening a valve — responsible designs include approval steps, limits, and the ability to override.

> **Key idea:** The person accountable for the outcome should always be able to see why a recommendation was made, change it, and stop it.

## Closing the loop: verification

The most valuable systems do not stop at the recommendation. They check what was actually done and what happened next: Did the irrigation run? How much water was applied? Did soil moisture recover as expected? This **verification** step builds trust, catches equipment problems, and produces the evidence that buyers, auditors and water authorities increasingly ask for.

Remember the loop from Module 1: **sense → predict → recommend → verify**. Each turn of the loop improves both the decisions and the data for the next season.`,
          script: `A prediction says what's likely. A recommendation says what to do. Getting from one to the other takes goals, constraints and context.

Say a model predicts a field will use seven millimeters tomorrow, and the soil is already near its limit. The recommendation also weighs pump capacity, remaining water allocation, power prices, forecast rain, and crop stage. The result might be: irrigate block four tonight for six hours — but skip block seven, because solid rain is forecast.

Good recommendations explain themselves: the reason, the confidence, the alternatives, and an evidence trail.

In agriculture, AI is mostly decision support. The system proposes; a person decides. Even with automation, you should be able to see why, change it, and stop it.

And the best systems close the loop by verifying what happened. Sense, predict, recommend, verify.`,
        },
        {
          id: "les_a1_quiz2",
          slug: "module-2-quiz",
          title: "Module 2 quiz",
          type: "quiz",
          minutes: 8,
          assessment: "asm_a1_q2",
          summary: "Check your understanding of data, models and recommendations.",
          body: "Five questions on data quality, model training and decision support. Retake as often as you like.",
        },
      ],
    },
    {
      id: "mod_a1_3",
      title: "AI across the season",
      summary: "Practical applications from planning to harvest.",
      lessons: [
        {
          id: "les_a1_planning",
          slug: "planning-and-planting",
          title: "Planning and planting",
          type: "text",
          minutes: 10,
          summary: "Using data and AI before the first seed goes in the ground.",
          body: `Many of the most valuable decisions of the season are made before planting. AI can help by bringing more evidence to those decisions.

## Field history and management zones

Fields are not uniform. Years of yield maps, soil surveys and satellite imagery often reveal consistent patterns: a low area that stays wet, a sandy ridge that dries out first. Algorithms can group these areas into **management zones** that respond differently to water, seed and fertilizer.

With zones, a grower can vary seeding rates, choose where to apply more or less nitrogen, or plan irrigation sets that match how each part of the field behaves.

## Variety and planting date decisions

Models trained on regional trials and weather records can estimate how varieties perform under different conditions and how planting date affects risk — for example, the chance of heat stress at flowering. These estimates are most useful when they reflect local trials, not only national averages.

## Scenario planning

AI tools can run "what if" scenarios quickly: What if the season is dry? What if water allocations are cut by 20%? What if input prices rise? Comparing scenarios helps you choose a plan that holds up across many possible futures, not only the expected one.

> **Field check:** When a tool recommends a seeding rate or variety, ask what data it was built on. Regional trial data from your soils and climate is far more relevant than a national average.

## Limits to keep in mind

Pre-season recommendations rest on long-range forecasts, which are uncertain. Treat them as a starting plan to be adjusted as the season unfolds, not a fixed prescription.`,
          script: `Some of the season's biggest decisions happen before planting — and AI can bring more evidence to them.

Fields aren't uniform. Years of yield maps, soil surveys and imagery reveal patterns, and algorithms can group them into management zones. With zones, you can vary seeding rates, fertilizer and irrigation sets to match how each part of the field behaves.

Models built on regional trials and weather history can estimate how varieties and planting dates trade off risk — like heat stress at flowering. Local trial data beats national averages every time.

And scenario planning lets you test a plan against a dry year, a water cut, or rising input costs.

Just remember: pre-season advice rests on long-range forecasts. Treat it as a starting plan you'll adjust.`,
        },
        {
          id: "les_a1_irrigation",
          slug: "irrigation-and-water",
          title: "Case study: irrigation and water management",
          type: "case_study",
          minutes: 15,
          summary: "How evapotranspiration, soil moisture and AI combine in irrigation scheduling.",
          body: `Irrigation is one of the clearest examples of AI creating value on a farm, because water decisions are frequent, costly and measurable.

## The water balance

Think of the root zone as a bank account for water.

- **Deposits:** rainfall and irrigation.
- **Withdrawals:** water used by the crop and evaporated from the soil — together called **evapotranspiration (ET)** — plus drainage below the roots.

The goal of irrigation scheduling is to keep the balance between a lower limit, where the crop starts to suffer stress, and an upper limit, beyond which water drains away and is wasted.

## Estimating crop water use

Crop water use is usually estimated in two steps:

1. **Reference evapotranspiration (ET₀)** is calculated from weather data — temperature, humidity, wind and solar radiation — for a standard reference crop.
2. A **crop coefficient (Kc)** adjusts ET₀ for the actual crop and its growth stage: **ETc = ET₀ × Kc**.

Machine learning can improve this estimate by learning from local sensors, canopy imagery and the farm's own history, especially where standard coefficients fit poorly.

## A scheduling scenario

> **Example:** A vineyard block has 40 mm of readily available water when the root zone is full. Soil moisture probes show 18 mm remain. Forecast ETc is 5 mm per day for the next four days, and no rain is expected.

Without irrigation, the block reaches its lower limit in about three and a half days (18 mm ÷ 5 mm/day). A scheduling system would recommend irrigating in the next two to three days, sized to refill the root zone without overfilling it, timed to available pump capacity and lower electricity prices at night.

If the forecast changes to 15 mm of rain on day two, a good system updates the recommendation — and explains why.

## Where AI adds value

- **Better water-use estimates** by combining weather, sensors and imagery.
- **Forecast-aware scheduling** that accounts for coming rain and heat.
- **Optimization** across many blocks, pump limits and water allocations.
- **Verification** — confirming from flow meters and soil moisture that irrigation happened as planned and had the expected effect.

## What can go wrong

A clogged emitter, a broken valve or a probe installed in an unrepresentative spot can all mislead the system. That is why the verification step matters: when observed soil moisture does not respond as predicted after an irrigation, it is a signal to investigate the field, not just the model.`,
          script: `Irrigation is one of the clearest wins for AI, because water decisions are frequent, costly and measurable.

Picture the root zone as a bank account. Rain and irrigation are deposits. Withdrawals are evapotranspiration — crop water use plus soil evaporation — and drainage.

Crop water use is usually estimated as reference evapotranspiration, calculated from weather, multiplied by a crop coefficient for the crop and its stage.

Here's a scenario. A vineyard block holds forty millimeters of readily available water. Only eighteen remain, and the crop will use about five per day. That's roughly three and a half days before stress. So the system recommends irrigating within two to three days, sized to refill without waste, timed for night-time power rates. If rain enters the forecast, the recommendation should change — and say why.

And when soil moisture doesn't respond after irrigation, check the field. It might be a clogged emitter, not the model.`,
        },
        {
          id: "les_a1_crop_health",
          slug: "crop-health-monitoring",
          title: "Crop health monitoring from above and up close",
          type: "text",
          minutes: 12,
          summary: "Satellite imagery, vegetation indices and computer vision for crop health.",
          body: `Healthy plants and stressed plants reflect light differently. AI uses that difference — captured by satellites, drones and cameras — to watch crops at a scale no scouting team could cover.

## How plants look to a satellite

Green leaves absorb most red light for photosynthesis and strongly reflect **near-infrared (NIR)** light. When plants are stressed, sparse or senescing, red reflectance rises and NIR reflectance falls.

The **Normalized Difference Vegetation Index (NDVI)** captures this contrast:

**NDVI = (NIR − Red) ÷ (NIR + Red)**

Values range from −1 to +1. Dense, healthy vegetation is typically high (often above 0.6); bare soil is low (around 0.1–0.2); water is usually negative.

## Reading NDVI maps wisely

NDVI is useful for spotting **where** a field differs, not for diagnosing **why**. A low-NDVI patch might be water stress, nutrient deficiency, disease, pests, a planting problem, or simply a different variety. The map tells you where to look; scouting tells you what you found.

> **Important:** Clouds, cloud shadows, haze and the time of day can distort satellite readings. Reliable services mask clouds and compare images over time rather than trusting a single snapshot.

Other indices exist for specific purposes — some are more sensitive to chlorophyll, others to water content or to dense canopies where NDVI saturates.

## Computer vision up close

On the ground, **computer vision** models analyze photos from phones, tractors or drones to:

- identify diseases and pests from leaf images;
- distinguish weeds from crops for targeted spraying;
- count fruit, flowers or plants to estimate yield.

These models are trained on large collections of labeled images. Their accuracy depends heavily on whether those images resemble your crop, your varieties and your lighting conditions.

## From detection to action

A good crop-monitoring workflow turns a detection into a prioritized task: *"Zone 3 shows declining vigor over 10 days. Scout the northeast corner first; check irrigation uniformity and look for signs of root disease."* The scout's findings then feed back into the system, improving future alerts.`,
          script: `Healthy plants reflect light differently from stressed ones, and AI uses that to watch whole farms.

Green leaves absorb red light and strongly reflect near-infrared. Stress flips that pattern. The Normalized Difference Vegetation Index — NDVI — captures it: near-infrared minus red, divided by their sum. Dense, healthy canopy scores high. Bare soil scores low.

But here's the key: NDVI tells you where a field differs, not why. A low patch could be water stress, nutrients, disease, pests or planting problems. The map tells you where to look; scouting tells you what you found. And watch out for clouds and haze — good services mask them and compare images over time.

Up close, computer vision reads photos to spot disease, separate weeds from crops, and count fruit — as long as it was trained on images like yours.`,
        },
        {
          id: "les_a1_harvest",
          slug: "harvest-markets-and-supply-chain",
          title: "Harvest, markets and the supply chain",
          type: "text",
          minutes: 10,
          summary: "Yield forecasting, market intelligence and logistics.",
          body: `As the season moves toward harvest, decisions shift from growing the crop to capturing its value.

## Yield forecasting

Yield forecasts combine crop growth models, weather to date and forecasts, imagery-based vigor, and sometimes counts from computer vision. Earlier forecasts are less certain; accuracy improves as the season progresses.

Forecasts support decisions such as:

- how much to sell forward, and when;
- how many workers, trucks and storage capacity to book;
- whether a late input is still worth applying.

## Market intelligence

Market intelligence tools gather prices, futures, export data, weather in competing regions and news to help anticipate price movements. AI can summarize these signals quickly and highlight unusual changes. No model can predict markets with certainty; treat market forecasts as one input to a risk-managed plan, not as a guarantee.

## Harvest timing and quality

Models that track crop maturity — sugar levels in grapes, moisture in grain, color in fruit — help schedule harvest for the best balance of quality, weather risk and logistics. Combined with labor and equipment availability, they can help sequence fields across an operation.

## Traceability and evidence

Buyers increasingly ask for proof of how a crop was produced: water use, inputs applied, certifications. Systems that record recommendations, actions and verification throughout the season make that evidence easy to produce — another reason the verify step of the loop matters.

> **Key idea:** At harvest, AI's value comes from reducing uncertainty in timing, quantity and price — and from documenting what was done.`,
          script: `Near harvest, the focus shifts from growing the crop to capturing its value.

Yield forecasts combine growth models, weather, imagery and sometimes fruit counts. They're uncertain early and sharpen as the season goes on — and they guide forward sales, labor, trucks and storage.

Market intelligence tools pull together prices, futures, export data and news, and AI can flag unusual moves fast. But no model predicts markets with certainty. Use forecasts inside a risk-managed plan.

Maturity models help time harvest for quality and logistics.

And increasingly, buyers want proof of how a crop was produced. Systems that record recommendations, actions and verification all season make that proof easy.`,
        },
        {
          id: "les_a1_quiz3",
          slug: "module-3-quiz",
          title: "Module 3 quiz",
          type: "quiz",
          minutes: 8,
          assessment: "asm_a1_q3",
          summary: "Check your understanding of AI across the season.",
          body: "Five questions on planning, irrigation, crop monitoring and harvest. Retake as often as you like.",
        },
      ],
    },
    {
      id: "mod_a1_4",
      title: "Using AI responsibly",
      summary: "Limits, data rights and confident, critical use.",
      lessons: [
        {
          id: "les_a1_limits",
          slug: "limits-and-when-to-challenge",
          title: "Limits, errors and when to challenge a recommendation",
          type: "text",
          minutes: 12,
          summary: "Recognizing failure modes and keeping human judgment in charge.",
          body: `Every AI system will sometimes be wrong. The goal is not blind trust or blanket rejection, but **calibrated trust**: knowing when a recommendation deserves confidence and when it deserves a second look.

## Common failure modes

**Bad inputs.** A failed sensor, a misplaced probe or a missing data feed produces confident nonsense. *Garbage in, garbage out.*

**Out-of-range conditions.** Models are least reliable in situations they rarely saw during training: extreme heat, a new variety, an unusual soil.

**Drift.** Conditions change over time, and a model that was accurate three years ago may no longer be.

**Bias.** If training data over-represents certain regions, farm sizes or crops, recommendations may be less accurate for operations that differ.

**Missing context.** The system does not know about the neighbor's herbicide drift, the broken pipe, or the contract that requires harvest next week.

**Automation bias.** People tend to over-trust machine output, especially when it is presented precisely. A number with two decimal places is not necessarily accurate.

## When to challenge a recommendation

Pause and investigate when:

- the recommendation contradicts what you see in the field;
- it is far outside the normal range for the season;
- the system shows low confidence, or does not show confidence at all;
- key data is missing, stale, or obviously wrong;
- the consequences of an error would be severe or hard to reverse.

> **Field check:** A simple rule — the bigger and less reversible the decision, the more evidence you should require before acting on an AI recommendation.

## How to challenge well

1. **Check the inputs.** Are the sensors reporting? Is the weather data current?
2. **Ask for the reason.** What data drove this suggestion?
3. **Look in the field.** Scout the area in question.
4. **Record what you decided and why.** Your override is valuable feedback that helps improve the system.

Challenging a recommendation is not a failure of the technology. It is how people and AI work well together.`,
          script: `Every AI system will sometimes be wrong. The goal isn't blind trust or blanket rejection — it's calibrated trust.

Know the common failures. Bad inputs from a failed sensor. Conditions the model rarely saw, like extreme heat or a new variety. Drift over time. Bias from training data that doesn't look like your farm. Missing context the system can't know. And automation bias — our habit of over-trusting precise-looking numbers.

Pause and investigate when a recommendation contradicts the field, falls far outside the normal range, shows low confidence, rests on stale data, or would be costly to get wrong.

Then challenge it well: check the inputs, ask for the reason, look in the field, and record what you decided. Your override is valuable feedback.

The bigger and less reversible the decision, the more evidence you should require.`,
        },
        {
          id: "les_a1_data_rights",
          slug: "data-ownership-privacy-and-trust",
          title: "Data ownership, privacy and trust",
          type: "text",
          minutes: 10,
          summary: "Practical principles for sharing farm data with confidence.",
          body: `Farm data can reveal yields, practices, finances and the location of people and assets. Sharing it can unlock valuable services — but it should always be a deliberate choice.

## Questions to ask any technology provider

- **Ownership:** Who owns the data I provide and the data the system generates about my farm?
- **Use:** What will the data be used for? Will it be used to train models? Will it be combined with other farms' data?
- **Sharing:** Will it be shared with or sold to third parties? Which ones, and why?
- **Access and portability:** Can I download my data in a usable format? Can I take it with me if I leave?
- **Deletion:** Can I delete my data, and what remains afterward?
- **Security:** How is the data protected? Who inside the company can see it?
- **Control:** Can I revoke access for a connected device or partner at any time?

Several agricultural organizations have published farm-data principles that address these questions; asking whether a provider follows them is a good starting point.

## Consent and permissions

Good systems ask for specific, informed permission — for example, allowing a connector to read irrigation controller data without granting it permission to change settings. Grant the least access needed for the job, and review connected services regularly.

## Aggregated and anonymized data

Combining data from many farms can improve models for everyone, such as better regional water-use estimates. Done well, aggregation removes information that could identify an individual farm. Ask how anonymization is performed and whether you can opt out.

## Trust is earned

> **Key idea:** Trustworthy agricultural AI is transparent about how it uses data, explains its recommendations, admits uncertainty, and leaves the farmer in control.

These same principles apply to the Academy itself. You can download or delete your learning data at any time from your account settings.`,
          script: `Farm data can reveal yields, practices, finances and the location of people and equipment. Sharing it can unlock great services — but it should always be your deliberate choice.

Before you connect anything, ask the provider: Who owns the data? What will it be used for — including training models? Is it shared or sold? Can I download it and take it with me? Can I delete it? How is it secured? Can I revoke access at any time?

Grant the least access needed — read-only if that's enough — and review connected services regularly.

Pooling data across farms can improve models for everyone, if it's properly anonymized and you can opt out.

Trustworthy agricultural AI is transparent, explains itself, admits uncertainty — and leaves you in control.`,
        },
        {
          id: "les_a1_exercise",
          slug: "evaluate-a-recommendation",
          title: "Practical exercise: evaluate an AI recommendation",
          type: "exercise",
          minutes: 15,
          summary: "Apply what you've learned to a realistic recommendation.",
          body: `In this exercise you will practice the critical review skills from this module on a realistic recommendation.

## The scenario

You manage a 60-hectare drip-irrigated tomato operation. On a Tuesday morning in mid-season, your decision-support system shows:

> *"Recommendation: Skip irrigation on Block C for the next 48 hours. Predicted crop water use: 3.1 mm/day. Soil moisture: 82% of field capacity. Confidence: high."*

When you drive past Block C, you notice the plants on the eastern edge look wilted in the late-morning heat, and yesterday's maximum temperature was 37 °C — much hotter than the 29 °C forecast the system used two days ago.

## Your task

Work through the checklist below. Write your reasoning in the **Notes** tab so you can return to it.

1. **Check the inputs.** Which input looks questionable? (Hint: compare the forecast temperature with what happened.)
2. **Check the sensors.** Where is the soil moisture probe installed? Could it be in a spot that does not represent the eastern edge?
3. **Look in the field.** What would you check on the wilted plants? Consider emitter clogging, pressure at the end of the line, and root health.
4. **Decide.** Would you follow, modify or override the recommendation? Why?
5. **Record and report.** What feedback would you give so the system — and your team — can learn from this?

## Discussion

A strong answer notices that the predicted water use was probably based on a forecast that turned out too cool, so actual demand was higher. A single probe reading 82% may not represent the eastern edge, especially if emitters there are clogged or pressure is low at the end of the lateral. A sensible decision might be to inspect the eastern edge immediately, run a short irrigation if inspection confirms dry soil, and report both the forecast miss and the possible uniformity problem.

There is rarely a single right answer — but there is always a right process: check inputs, check context, look in the field, decide, and record.`,
          interactive: {
            kind: "checklist",
            title: "Review checklist",
            items: [
              "I compared the inputs the system used with what actually happened",
              "I considered whether the sensor location represents the area of concern",
              "I listed what I would inspect in the field",
              "I decided whether to follow, modify or override — and wrote down why",
              "I identified the feedback to report to my team and the system",
            ],
          },
          script: `Let's practice. You manage a drip-irrigated tomato operation. The system says: skip irrigation on Block C for forty-eight hours — soil moisture is high, confidence is high.

But on the eastern edge, plants are wilting at midday, and yesterday hit thirty-seven degrees — far hotter than the twenty-nine the system expected.

Work through it. The forecast input was too cool, so real water demand was higher. One probe may not represent the eastern edge, especially if emitters are clogged or pressure drops at the end of the line.

A sensible call: inspect now, run a short irrigation if the soil is dry, and report both the forecast miss and the uniformity problem.

There's rarely one right answer — but there's always a right process.`,
        },
        {
          id: "les_a1_summary",
          slug: "summary-and-next-steps",
          title: "Course summary and next steps",
          type: "text",
          minutes: 6,
          summary: "Key takeaways and how to prepare for the final exam.",
          body: `Congratulations on reaching the end of the course. Let's bring the main ideas together.

## Key takeaways

- **AI is a toolbox**, not a single technology. Rules, machine learning, deep learning and generative AI suit different problems.
- **Data is the foundation.** Accuracy, completeness, timeliness, consistency and representativeness determine what any model can do.
- **Models learn from examples** and must be validated on data they have never seen. Every prediction has uncertainty, and models can drift.
- **Recommendations combine predictions with goals, constraints and context.** Good ones explain themselves.
- **The loop matters:** sense → predict → recommend → verify.
- **Across the season**, AI supports planning, irrigation, crop monitoring, harvest timing, marketing and traceability.
- **Use calibrated trust.** Challenge recommendations that conflict with the field, rest on poor data, or carry high stakes.
- **Your data deserves care.** Know who owns it, how it is used, and how to take it back.

## Preparing for the final exam

The final exam covers all four modules. It draws 20 questions from a larger bank and gives you 30 minutes. You need **80%** to pass.

> **Tip:** Review your notes and the module quizzes. If you missed a quiz question, open the lesson it points to before the exam.

## Where to go next

- **Agricultural Data Fundamentals** goes deeper into data sources and quality.
- **Remote Sensing and Satellite Intelligence** expands on imagery and vegetation indices.
- **AI-Powered Irrigation** applies these ideas to water management in detail.

Thank you for learning with AGRO-AI Academy. When you are ready, open the final exam from the course menu.`,
          script: `You've reached the end of the course. Let's bring it together.

AI is a toolbox. Data is the foundation. Models learn from examples, must be validated on new data, and always carry uncertainty. Recommendations combine predictions with goals, constraints and context — and good ones explain themselves.

Remember the loop: sense, predict, recommend, verify. Use calibrated trust: challenge advice that conflicts with the field or carries high stakes. And treat your data with care.

The final exam has twenty questions, thirty minutes, and an eighty percent pass mark. Review your notes and quizzes first.

Thank you for learning with AGRO-AI Academy. Good luck — I'll see you in the next course.`,
        },
      ],
    },
  ],

  assessments: [
    { id: "asm_a1_q1", kind: "quiz", title: "Module 1 quiz", passing: 60, feedback: "full", rules: [{ bank: "bnk_a1_m1", count: 5 }] },
    { id: "asm_a1_q2", kind: "quiz", title: "Module 2 quiz", passing: 60, feedback: "full", rules: [{ bank: "bnk_a1_m2", count: 5 }] },
    { id: "asm_a1_q3", kind: "quiz", title: "Module 3 quiz", passing: 60, feedback: "full", rules: [{ bank: "bnk_a1_m3", count: 5 }] },
    {
      id: "asm_a1_exam",
      kind: "exam",
      certification: true,
      title: "Final exam: Introduction to AI in Agriculture",
      instructions:
        "This exam covers all four modules. You have 30 minutes to answer 20 questions drawn at random from the course question bank. A score of 80% or higher earns your certificate. Your answers save automatically.",
      passing: 80,
      timeLimit: 1800,
      maxAttempts: null,
      cooldown: 60,
      feedback: "correctness",
      rules: [
        { bank: "bnk_a1_exam", difficulty: "easy", count: 6 },
        { bank: "bnk_a1_exam", difficulty: "medium", count: 10 },
        { bank: "bnk_a1_exam", difficulty: "hard", count: 4 },
      ],
    },
  ],

  banks: [
    {
      id: "bnk_a1_m1",
      title: "A1 · Module 1 practice",
      questions: [
        { id: "q_a1m1_1", type: "single", difficulty: "easy", lesson: "les_a1_what_is_ai", prompt: "Which statement best describes machine learning?", options: [["A system that follows rules written in advance by people", false], ["A system that learns patterns from examples of data", true], ["A system that always produces correct answers", false], ["A type of sensor used in fields", false]], explanation: "Machine learning builds models by learning relationships from examples rather than from hand-written rules." },
        { id: "q_a1m1_2", type: "true_false", difficulty: "easy", lesson: "les_a1_what_is_ai", prompt: "Generative AI tools can state false information with complete confidence.", answer: true, explanation: "Generative models produce plausible output, not verified facts, so important claims must be checked." },
        { id: "q_a1m1_3", type: "single", difficulty: "easy", lesson: "les_a1_what_is_ai", prompt: "An irrigation controller starts the pump whenever soil moisture falls below 25%. This is an example of…", options: [["A rule-based system", true], ["Deep learning", false], ["Generative AI", false], ["Computer vision", false]], explanation: "The logic is a fixed rule written by a person, not learned from data." },
        { id: "q_a1m1_4", type: "ordering", difficulty: "medium", lesson: "les_a1_why_now", prompt: "Put the steps of the AI decision loop in order.", order: ["Sense", "Predict", "Recommend", "Verify"], explanation: "Sense → predict → recommend → verify, and each turn improves the next." },
        { id: "q_a1m1_5", type: "multiple", difficulty: "medium", lesson: "les_a1_why_now", prompt: "Which developments made agricultural AI practical in recent years? Select all that apply.", options: [["Abundant data from satellites and sensors", true], ["Cheap, connected computing", true], ["Mature machine learning methods", true], ["A guarantee that models are always accurate", false]], explanation: "Data, computing and methods matured together. No model is guaranteed to be accurate." },
        { id: "q_a1m1_6", type: "single", difficulty: "medium", lesson: "les_a1_what_is_ai", prompt: "Which kind of AI is especially strong at interpreting images such as leaf photos?", options: [["Deep learning", true], ["Spreadsheet formulas", false], ["Rule-based thresholds", false], ["Market forecasting", false]], explanation: "Deep learning methods excel at complex data such as images and sound." },
      ],
    },
    {
      id: "bnk_a1_m2",
      title: "A1 · Module 2 practice",
      questions: [
        { id: "q_a1m2_1", type: "single", difficulty: "easy", lesson: "les_a1_data", prompt: "A rain gauge installed under a tree mostly harms which quality of data?", options: [["Accuracy", true], ["Timeliness", false], ["Consistency of units", false], ["Portability", false]], explanation: "The measurement no longer reflects actual rainfall, so its accuracy suffers." },
        { id: "q_a1m2_2", type: "single", difficulty: "medium", lesson: "les_a1_models", prompt: "Why do data scientists keep some data aside during training?", options: [["To test the model on examples it has never seen", true], ["To make training faster", false], ["To hide data from farmers", false], ["Because sensors produce too much data", false]], explanation: "Held-out validation data gives an honest measure of how well a model works on new cases." },
        { id: "q_a1m2_3", type: "matching", difficulty: "medium", lesson: "les_a1_models", prompt: "Match each model type with what it does.", pairs: [["Regression", "Predicts a number"], ["Classification", "Assigns a category"], ["Forecasting", "Predicts change over time"], ["Optimization", "Finds the best plan within constraints"]], explanation: "Each model family answers a different kind of question." },
        { id: "q_a1m2_4", type: "true_false", difficulty: "easy", lesson: "les_a1_recommendations", prompt: "In agricultural decision support, the system proposes and a person decides.", answer: true, explanation: "Most agricultural AI is decision support; responsibility stays with people." },
        { id: "q_a1m2_5", type: "multiple", difficulty: "medium", lesson: "les_a1_recommendations", prompt: "What should a good recommendation show you? Select all that apply.", options: [["The reason behind it", true], ["How confident the system is", true], ["An evidence trail you can check later", true], ["Only a single number with no explanation", false]], explanation: "Explanations, confidence and evidence make recommendations judgeable." },
        { id: "q_a1m2_6", type: "single", difficulty: "hard", lesson: "les_a1_models", prompt: "A model that was accurate three years ago now performs poorly after a switch to new varieties. This is best described as…", options: [["Drift", true], ["Overfitting to the validation set", false], ["Automation bias", false], ["Cloud masking", false]], explanation: "Drift occurs when conditions change so past data no longer represents the present." },
      ],
    },
    {
      id: "bnk_a1_m3",
      title: "A1 · Module 3 practice",
      questions: [
        { id: "q_a1m3_1", type: "single", difficulty: "easy", lesson: "les_a1_crop_health", prompt: "Healthy green vegetation strongly reflects which kind of light?", options: [["Near-infrared", true], ["Red", false], ["Ultraviolet", false], ["Blue", false]], explanation: "Healthy leaves reflect near-infrared strongly and absorb red light." },
        { id: "q_a1m3_2", type: "short_answer", difficulty: "medium", lesson: "les_a1_crop_health", prompt: "What is the common four-letter abbreviation for the Normalized Difference Vegetation Index?", accepted: ["NDVI"], explanation: "NDVI = (NIR − Red) ÷ (NIR + Red)." },
        { id: "q_a1m3_3", type: "single", difficulty: "medium", lesson: "les_a1_irrigation", prompt: "Crop water use (ETc) is commonly estimated as…", options: [["Reference evapotranspiration × crop coefficient", true], ["Rainfall − irrigation", false], ["Soil moisture × yield", false], ["NDVI × temperature", false]], explanation: "Reference evapotranspiration (ET₀) is calculated from weather data for a standard reference crop; the crop coefficient (Kc) adjusts it for the actual crop and its growth stage, so ETc = ET₀ × Kc. The other options combine quantities that do not describe crop water use." },
        { id: "q_a1m3_4", type: "true_false", difficulty: "easy", lesson: "les_a1_crop_health", prompt: "A low-NDVI patch tells you exactly what is wrong with the crop.", answer: false, explanation: "NDVI shows where a field differs; scouting determines why." },
        { id: "q_a1m3_5", type: "single", difficulty: "medium", lesson: "les_a1_planning", prompt: "Grouping areas of a field that respond similarly to water and inputs creates…", options: [["Management zones", true], ["Validation sets", false], ["Crop coefficients", false], ["Market signals", false]], explanation: "Management zones group parts of a field that behave alike, such as a low area that stays wet or a sandy ridge that dries first, so seeding, nitrogen and irrigation can be matched to each zone instead of treating the whole field as uniform." },
        { id: "q_a1m3_6", type: "single", difficulty: "hard", lesson: "les_a1_irrigation", prompt: "A root zone holds 16 mm of readily available water and the crop uses 4 mm per day with no rain. About how many days until it reaches its lower limit?", options: [["4 days", true], ["2 days", false], ["8 days", false], ["16 days", false]], explanation: "16 mm ÷ 4 mm/day = 4 days." },
      ],
    },
    {
      id: "bnk_a1_exam",
      title: "A1 · Certification exam bank",
      cases: [
        {
          id: "cas_a1_orchard",
          title: "Case: an orchard irrigation recommendation",
          body: "A citrus grower receives this recommendation: *“Irrigate Block 2 for 8 hours tonight. Predicted water use: 6 mm/day. Confidence: medium.”* The soil moisture probe in Block 2 has not reported for three days, and the system is using its last known reading. A heat wave is forecast for the next four days.",
        },
      ],
      questions: [
        // Easy
        { id: "q_a1x_e1", type: "single", difficulty: "easy", lesson: "les_a1_what_is_ai", prompt: "Most of what people call “AI” today is…", options: [["Machine learning", true], ["Hand-written rules", false], ["Mechanical automation", false], ["Satellite photography", false]], explanation: "Machine learning is the dominant approach behind modern AI." },
        { id: "q_a1x_e2", type: "true_false", difficulty: "easy", lesson: "les_a1_what_is_ai", prompt: "AI can carry legal and practical responsibility for a farm decision.", answer: false, explanation: "Responsibility for decisions stays with people." },
        { id: "q_a1x_e3", type: "single", difficulty: "easy", lesson: "les_a1_data", prompt: "A moisture sensor stops reporting for a week during a heat wave. Which data quality is most affected?", options: [["Completeness", true], ["Consistency of units", false], ["Representativeness of soil types", false], ["Ownership", false]], explanation: "The data has a gap exactly when it matters most." },
        { id: "q_a1x_e4", type: "single", difficulty: "easy", lesson: "les_a1_crop_health", prompt: "On an NDVI map, which surface usually has the lowest values?", options: [["Open water", true], ["Dense healthy canopy", false], ["Young crop", false], ["Orchard rows", false]], explanation: "Water typically has negative NDVI values." },
        { id: "q_a1x_e5", type: "true_false", difficulty: "easy", lesson: "les_a1_recommendations", prompt: "Verifying whether an irrigation actually ran and had the expected effect helps catch equipment problems.", answer: true, explanation: "Verification closes the loop and builds trust." },
        { id: "q_a1x_e6", type: "single", difficulty: "easy", lesson: "les_a1_data_rights", prompt: "When connecting a device that only needs to read irrigation data, you should grant…", options: [["The least access needed, such as read-only", true], ["Full control of every setting", false], ["Access to all of your farm records", false], ["Permanent access that cannot be revoked", false]], explanation: "Grant the least access the job needs. A connector that only reads irrigation data does not need to change settings, see your other records or keep access forever, and the less access it holds, the less harm it can do if it is misused or compromised. Review connected services regularly." },
        { id: "q_a1x_e7", type: "single", difficulty: "easy", lesson: "les_a1_why_now", prompt: "According to the FAO, roughly what share of global freshwater withdrawals is used by agriculture?", options: [["About 70%", true], ["About 10%", false], ["About 30%", false], ["Almost 100%", false]], explanation: "Agriculture accounts for roughly 70% of global freshwater withdrawals." },
        { id: "q_a1x_e8", type: "multiple", difficulty: "easy", lesson: "les_a1_data", prompt: "Which of these are sources of agricultural data? Select all that apply.", options: [["Weather stations", true], ["Satellite imagery", true], ["Irrigation flow meters", true], ["Your own scouting notes", true], ["A vendor's claim about how accurate its model is", false]], explanation: "Weather stations, satellite imagery, flow meters and scouting notes all record what is actually happening on the farm. A vendor's accuracy claim is not farm data: it is a statement to check against evidence from your own fields." },
        { id: "q_a1x_e9", type: "short_answer", difficulty: "easy", lesson: "les_a1_irrigation", prompt: "Crop water use plus soil evaporation is called evapo______ (complete the word).", accepted: ["transpiration", "evapotranspiration"], explanation: "Evapotranspiration (ET) combines plant transpiration and soil evaporation." },
        // Medium
        { id: "q_a1x_m1", type: "single", difficulty: "medium", lesson: "les_a1_models", prompt: "A vendor says their model “fits our historical data perfectly.” What is the best response?", options: [["Ask how it performs on data it never saw during training", true], ["Adopt it immediately", false], ["Assume it will be perfect on your farm", false], ["Ignore validation because the fit is perfect", false]], explanation: "A perfect historical fit can signal memorization; held-out validation is the honest test." },
        { id: "q_a1x_m2", type: "matching", difficulty: "medium", lesson: "les_a1_data", prompt: "Match each data problem with the quality it violates.", pairs: [["Inches mixed with millimeters", "Consistency"], ["Probe placed in an unusually wet spot", "Accuracy"], ["Last month's soil moisture used for today's decision", "Timeliness"], ["Model trained only on sandy soils, used on clay", "Representativeness"]], explanation: "Each issue undermines a different dimension of data quality." },
        { id: "q_a1x_m3", type: "multiple", difficulty: "medium", lesson: "les_a1_limits", prompt: "Which situations should prompt you to investigate before acting on a recommendation? Select all that apply.", options: [["It contradicts what you see in the field", true], ["Key input data is stale", true], ["The decision is costly and hard to reverse", true], ["It matches field observations and the data is current", false]], explanation: "Conflicts, poor data and high stakes all warrant a second look." },
        { id: "q_a1x_m4", type: "single", difficulty: "medium", lesson: "les_a1_crop_health", prompt: "Why do reliable satellite services compare images over time instead of using a single snapshot?", options: [["Clouds, shadows and haze can distort individual images", true], ["Satellites only work at night", false], ["NDVI never changes during a season", false], ["Single images are illegal to use", false]], explanation: "Comparing over time and masking clouds reduces false alarms." },
        { id: "q_a1x_m5", type: "ordering", difficulty: "medium", lesson: "les_a1_limits", prompt: "Order these steps for challenging a recommendation well.", order: ["Check the inputs", "Ask for the reason", "Look in the field", "Record what you decided and why"], explanation: "Check inputs, understand the reason, verify in the field, then record your decision as feedback." },
        { id: "q_a1x_m6", type: "single", difficulty: "medium", lesson: "les_a1_recommendations", prompt: "Which element turns a water-use prediction into an irrigation recommendation?", options: [["Combining it with goals, constraints and context", true], ["Rounding it to whole millimeters", false], ["Displaying it on a map", false], ["Sending it by email", false]], explanation: "Recommendations weigh predictions against goals, constraints and context." },
        { id: "q_a1x_m7", type: "single", difficulty: "medium", lesson: "les_a1_what_is_ai", prompt: "What is the main risk of using a generative AI assistant to answer “How much nitrogen should I apply to field 12?”", options: [["It may give a plausible but unverified answer", true], ["It cannot write in full sentences", false], ["It only works with images", false], ["It always refuses agricultural questions", false]], explanation: "Generative AI predicts plausible text; important numbers must be checked against trusted data and expertise." },
        { id: "q_a1x_m8", type: "true_false", difficulty: "medium", lesson: "les_a1_models", prompt: "A forecast of “6.2 mm, likely between 5.6 and 6.8 mm” is more informative than “6.2 mm” alone.", answer: true, explanation: "Communicating uncertainty helps you judge how much to rely on a prediction." },
        { id: "q_a1x_m9", type: "single", difficulty: "medium", lesson: "les_a1_harvest", prompt: "How should a market price forecast generated by AI be used?", options: [["As one input to a risk-managed marketing plan", true], ["As a guaranteed price", false], ["Only after harvest is complete", false], ["Never, because markets cannot be analyzed", false]], explanation: "Market forecasts are uncertain and belong inside a broader risk plan." },
        { id: "q_a1x_m10", type: "multiple", difficulty: "medium", lesson: "les_a1_data_rights", prompt: "Which questions should you ask a provider before sharing farm data? Select all that apply.", options: [["Can I download my data and take it with me?", true], ["Will my data be used to train models?", true], ["Can I delete my data?", true], ["What color is the company logo?", false]], explanation: "Portability, use and deletion are central to data rights." },
        { id: "q_a1x_m11", type: "single", difficulty: "medium", lesson: "les_a1_planning", prompt: "Why are local trial results usually more relevant than national averages for variety selection?", options: [["They reflect your soils and climate", true], ["They are always larger datasets", false], ["They never contain errors", false], ["National averages are not allowed in models", false]], explanation: "Representative data gives more relevant recommendations." },
        { id: "q_a1x_m12", type: "case", difficulty: "medium", case: "cas_a1_orchard", lesson: "les_a1_limits", baseType: "single", prompt: "In the orchard case, what is the most important weakness in the recommendation's inputs?", options: [["The soil moisture probe has not reported for three days", true], ["The recommendation is for nighttime irrigation", false], ["The block is named Block 2", false], ["Citrus does not need irrigation", false]], explanation: "A stale sensor reading means the system may not know the current soil moisture." },
        { id: "q_a1x_m13", type: "case", difficulty: "medium", case: "cas_a1_orchard", lesson: "les_a1_limits", baseType: "multiple", prompt: "In the orchard case, which actions are sensible? Select all that apply.", options: [["Inspect the probe and restore its data feed", true], ["Check soil moisture in Block 2 by hand", true], ["Consider the forecast heat wave when deciding how much to irrigate", true], ["Disable all recommendations permanently", false]], explanation: "Fix the data, verify in the field, and account for the forecast." },
        { id: "q_a1x_m14", type: "single", difficulty: "medium", lesson: "les_a1_irrigation", prompt: "Which statement about the crop coefficient (Kc) is correct?", options: [["It adjusts reference ET for the crop and its growth stage", true], ["It measures rainfall", false], ["It is the same for every crop and stage", false], ["It replaces weather data", false]], explanation: "Kc varies by crop and stage: ETc = ET₀ × Kc." },
        // Hard
        { id: "q_a1x_h1", type: "single", difficulty: "hard", lesson: "les_a1_irrigation", prompt: "A root zone holds 30 mm of readily available water when full. A probe shows 12 mm remaining, forecast ETc is 4 mm/day, and 8 mm of effective rain is expected on day 2. Without irrigation, roughly when will the lower limit be reached?", options: [["About day 5", true], ["About day 3", false], ["About day 1", false], ["It will never be reached", false]], explanation: "12 mm − 4 (day 1) = 8; −4 + 8 (day 2) = 12; then 4 mm/day lasts about 3 more days, reaching the limit around day 5." },
        { id: "q_a1x_h2", type: "single", difficulty: "hard", lesson: "les_a1_crop_health", prompt: "A pixel has near-infrared reflectance of 0.50 and red reflectance of 0.10. What is its NDVI?", options: [["About 0.67", true], ["About 0.40", false], ["About 0.20", false], ["About 5.0", false]], explanation: "(0.50 − 0.10) ÷ (0.50 + 0.10) = 0.40 ÷ 0.60 ≈ 0.67." },
        { id: "q_a1x_h3", type: "multiple", difficulty: "hard", lesson: "les_a1_limits", prompt: "A disease-detection app trained mostly on images from one country performs poorly on your farm. Which explanations are plausible? Select all that apply.", options: [["Training data was not representative of your varieties", true], ["Lighting and camera conditions differ", true], ["The app is affected by bias in its training data", true], ["The app works perfectly; your crop must be healthy", false]], explanation: "Representativeness and bias limit how well models transfer to new conditions." },
        { id: "q_a1x_h4", type: "single", difficulty: "hard", lesson: "les_a1_limits", prompt: "Staff accept every system recommendation because the numbers look precise. This tendency is called…", options: [["Automation bias", true], ["Data drift", false], ["Cloud masking", false], ["Supervised learning", false]], explanation: "Automation bias is the tendency to over-trust machine output." },
        { id: "q_a1x_h5", type: "matching", difficulty: "hard", lesson: "les_a1_why_now", prompt: "Match each step of the decision loop with an example.", pairs: [["Sense", "Satellite imagery reveals a stressed zone"], ["Predict", "A model estimates tomorrow's water use"], ["Recommend", "Irrigate block 4 tonight for 6 hours"], ["Verify", "Flow meters confirm 18 mm was applied"]], explanation: "Each step of sense → predict → recommend → verify has a distinct role." },
        { id: "q_a1x_h6", type: "case", difficulty: "hard", case: "cas_a1_orchard", lesson: "les_a1_limits", baseType: "true_false", prompt: "In the orchard case, the “medium” confidence label means the grower can safely skip any field check.", answer: false, explanation: "Medium confidence combined with a stale sensor is a reason to check, not to skip verification." },
        { id: "q_a1x_h7", type: "single", difficulty: "hard", lesson: "les_a1_data_rights", prompt: "Pooling data from many farms can improve regional models. What makes this acceptable from a data-rights perspective?", options: [["Proper anonymization and clear consent, including an opt-out", true], ["Selling the combined dataset to the highest bidder", false], ["Hiding the practice from farmers", false], ["Using it only if a competitor asks", false]], explanation: "Aggregation should protect identities and respect farmers' choices." },
      ],
    },
  ],
};
