// The Academy's academic roadmap: programs, learning paths, instructors and
// course records. Courses here are DRAFTS unless their full instruction lives in
// ./courses/*.js. The roadmap reflects the planned curriculum, not a claim that
// every AGRO-AI capability described already exists; product courses must be
// checked against the live product before publication.

export const PROGRAMS = [
  {
    id: "prg_a",
    slug: "foundations-of-agricultural-ai",
    code: "A",
    title: "Foundations of Agricultural AI",
    summary: "The concepts, data and methods behind artificial intelligence in agriculture — for everyone, no technical background required.",
  },
  {
    id: "prg_b",
    slug: "agro-ai-enterprise-portal",
    code: "B",
    title: "AGRO-AI Enterprise Portal",
    summary: "Hands-on training for teams that use the AGRO-AI Enterprise Portal in day-to-day agricultural operations.",
  },
  {
    id: "prg_c",
    slug: "agro-ai-platform-api",
    code: "C",
    title: "AGRO-AI Platform API",
    summary: "For developers and integrators connecting agricultural systems to AGRO-AI's intelligence through the Platform API.",
  },
  {
    id: "prg_d",
    slug: "applied-agricultural-intelligence",
    code: "D",
    title: "Applied Agricultural Intelligence",
    summary: "Applying AI to irrigation, water, crop monitoring, risk and the operational decisions of a working farm.",
  },
  {
    id: "prg_e",
    slug: "advanced-agricultural-ai",
    code: "E",
    title: "Advanced Agricultural AI",
    summary: "Computer vision, satellite analysis, predictive analytics, AI agents and robotics for advanced practitioners.",
  },
];

export const INSTRUCTORS = [
  {
    id: "ins_faculty",
    slug: "agro-ai-academy-faculty",
    name: "AGRO-AI Academy Faculty",
    title: "AGRO-AI agronomy, data science and product teams",
    bio: "Courses are written and reviewed by the AGRO-AI team, drawing on its work building irrigation, field and market intelligence for agricultural operations in the Americas.",
    status: "active",
    sort: 0,
  },
  {
    id: "ins_joshua",
    slug: "joshua",
    name: "Joshua",
    title: "AI presenter for AGRO-AI Academy video lessons",
    bio: "Joshua presents Academy video lessons. Lesson scripts are written and reviewed by the AGRO-AI Academy Faculty.",
    is_ai_avatar: 1,
    disclosure: "Joshua is an AI-generated presenter (Synthesia). He is not a real person.",
    // Hidden until the first approved Joshua videos are published.
    status: "hidden",
    sort: 1,
  },
];

const d = (o) => ({ status: "draft", level: "beginner", ...o });

/** Course records for the full roadmap. Full instruction lives in ./courses. */
export const COURSE_RECORDS = [
  // Program A
  d({ id: "crs_a1", slug: "introduction-to-ai-in-agriculture", program: "prg_a", sort: 1, title: "Introduction to Artificial Intelligence in Agriculture", subtitle: "What AI is, how it works on the farm, and how to use it responsibly.", minutes: 150, topics: ["ai-foundations", "data", "precision-agriculture", "ethics"], audience: ["grower", "agronomist", "farm_manager", "operator", "student", "researcher", "advisor"] }),
  d({ id: "crs_a2", slug: "agricultural-data-fundamentals", program: "prg_a", sort: 2, title: "Agricultural Data Fundamentals", subtitle: "The sources, quality and structure of the data that powers agricultural AI.", minutes: 180, topics: ["data"], audience: ["agronomist", "farm_manager", "student", "researcher"] }),
  d({ id: "crs_a3", slug: "machine-learning-in-agriculture", program: "prg_a", sort: 3, level: "intermediate", title: "Machine Learning in Agriculture", subtitle: "How models learn from agricultural data, and how to judge whether they work.", minutes: 240, topics: ["machine-learning", "data"], audience: ["agronomist", "student", "researcher", "developer"] }),
  d({ id: "crs_a4", slug: "remote-sensing-and-satellite-intelligence", program: "prg_a", sort: 4, level: "intermediate", title: "Remote Sensing and Satellite Intelligence", subtitle: "Reading fields from above: spectral imagery, vegetation indices and their limits.", minutes: 210, topics: ["remote-sensing", "crop-monitoring"], audience: ["agronomist", "farm_manager", "student", "researcher"] }),
  d({ id: "crs_a5", slug: "ai-for-precision-agriculture", program: "prg_a", sort: 5, level: "intermediate", title: "AI for Precision Agriculture", subtitle: "Variable-rate decisions, management zones and site-specific recommendations.", minutes: 210, topics: ["precision-agriculture"], audience: ["grower", "agronomist", "farm_manager"] }),
  d({ id: "crs_a6", slug: "responsible-agricultural-ai", program: "prg_a", sort: 6, title: "Agricultural AI Ethics and Responsible Deployment", subtitle: "Data rights, fairness, transparency and accountability in farm AI.", minutes: 120, topics: ["ethics"], audience: ["grower", "farm_manager", "advisor", "researcher", "developer"] }),
  // Program B
  d({ id: "crs_b1", slug: "introduction-to-agro-ai", program: "prg_b", sort: 1, title: "Introduction to AGRO-AI", subtitle: "What AGRO-AI does, who it serves, and how its products fit together.", minutes: 45, topics: ["platform"], audience: ["grower", "farm_manager", "operator", "agronomist"] }),
  d({ id: "crs_b2", slug: "getting-started-with-the-enterprise-portal", program: "prg_b", sort: 2, title: "Getting Started with the Enterprise Portal", subtitle: "Sign in, set up your workspace and find your way around the Portal.", minutes: 60, topics: ["platform"], audience: ["farm_manager", "operator", "agronomist"] }),
  d({ id: "crs_b3", slug: "navigating-the-platform", program: "prg_b", sort: 3, title: "Navigating the Platform", subtitle: "Workspaces, fields, roles and the daily workflow in the Portal.", minutes: 60, topics: ["platform"], audience: ["farm_manager", "operator"] }),
  d({ id: "crs_b4", slug: "understanding-recommendations", program: "prg_b", sort: 4, title: "Understanding Recommendations", subtitle: "How AGRO-AI recommendations are produced, explained and verified.", minutes: 75, topics: ["platform", "irrigation"], audience: ["grower", "farm_manager", "operator", "agronomist"] }),
  d({ id: "crs_b5", slug: "field-intelligence", program: "prg_b", sort: 5, title: "Field Intelligence", subtitle: "Using field-level insight to plan and act.", minutes: 75, topics: ["platform", "crop-monitoring"], audience: ["grower", "agronomist", "farm_manager"] }),
  d({ id: "crs_b6", slug: "crop-intelligence", program: "prg_b", sort: 6, title: "Crop Intelligence", subtitle: "Monitoring crop condition and stage with AGRO-AI.", minutes: 75, topics: ["platform", "crop-monitoring"], audience: ["grower", "agronomist"] }),
  d({ id: "crs_b7", slug: "market-intelligence", program: "prg_b", sort: 7, title: "Market Intelligence", subtitle: "Reading market signals for agricultural decisions.", minutes: 60, topics: ["platform", "risk"], audience: ["farm_manager", "advisor"] }),
  d({ id: "crs_b8", slug: "product-intelligence", program: "prg_b", sort: 8, title: "Product Intelligence", subtitle: "Input and product decisions supported by AGRO-AI.", minutes: 60, topics: ["platform"], audience: ["farm_manager", "agronomist", "advisor"] }),
  d({ id: "crs_b9", slug: "reporting-and-verification", program: "prg_b", sort: 9, title: "Reporting and Verification", subtitle: "Reports, execution tracking and evidence for auditors and partners.", minutes: 60, topics: ["platform"], audience: ["farm_manager", "advisor"] }),
  d({ id: "crs_b10", slug: "agro-ai-in-agricultural-operations", program: "prg_b", sort: 10, level: "intermediate", title: "Using AGRO-AI in Agricultural Operations", subtitle: "Bringing AGRO-AI into the routines of a working operation.", minutes: 90, topics: ["platform"], audience: ["farm_manager", "operator"] }),
  // Program C
  d({ id: "crs_c1", slug: "introduction-to-the-platform-api", program: "prg_c", sort: 1, level: "intermediate", title: "Introduction to the Platform API", subtitle: "What the AGRO-AI Platform API offers developers and integrators.", minutes: 60, topics: ["api"], audience: ["developer"] }),
  d({ id: "crs_c2", slug: "api-authentication-and-access", program: "prg_c", sort: 2, level: "intermediate", title: "Authentication and API Access", subtitle: "Keys, scopes and secure access to the Platform API.", minutes: 60, topics: ["api"], audience: ["developer"] }),
  d({ id: "crs_c3", slug: "understanding-api-responses", program: "prg_c", sort: 3, level: "intermediate", title: "Understanding API Responses", subtitle: "Reading results, provenance, confidence and errors.", minutes: 60, topics: ["api"], audience: ["developer"] }),
  d({ id: "crs_c4", slug: "agricultural-intelligence-workflows", program: "prg_c", sort: 4, level: "advanced", title: "Agricultural Intelligence Workflows", subtitle: "Composing API calls into end-to-end agricultural workflows.", minutes: 90, topics: ["api"], audience: ["developer"] }),
  d({ id: "crs_c5", slug: "building-integrations", program: "prg_c", sort: 5, level: "advanced", title: "Building Integrations", subtitle: "Connecting farm systems, controllers and data platforms.", minutes: 120, topics: ["api"], audience: ["developer"] }),
  d({ id: "crs_c6", slug: "production-integration-practices", program: "prg_c", sort: 6, level: "advanced", title: "Production Integration Practices", subtitle: "Reliability, security, monitoring and change management.", minutes: 90, topics: ["api"], audience: ["developer"] }),
  // Program D
  d({ id: "crs_d1", slug: "ai-powered-irrigation", program: "prg_d", sort: 1, level: "intermediate", title: "AI-Powered Irrigation", subtitle: "Scheduling irrigation with evapotranspiration, sensors and AI.", minutes: 180, topics: ["irrigation", "precision-agriculture"], audience: ["grower", "operator", "agronomist", "farm_manager"] }),
  d({ id: "crs_d2", slug: "agricultural-water-management", program: "prg_d", sort: 2, level: "intermediate", title: "Agricultural Water Management", subtitle: "Water budgets, allocation and conservation at farm and basin scale.", minutes: 180, topics: ["irrigation"], audience: ["farm_manager", "agronomist", "advisor"] }),
  d({ id: "crs_d3", slug: "crop-monitoring", program: "prg_d", sort: 3, level: "intermediate", title: "Crop Monitoring", subtitle: "Combining scouting, sensors and imagery to track crop condition.", minutes: 150, topics: ["crop-monitoring", "remote-sensing"], audience: ["grower", "agronomist", "operator"] }),
  d({ id: "crs_d4", slug: "yield-and-risk-intelligence", program: "prg_d", sort: 4, level: "intermediate", title: "Yield and Risk Intelligence", subtitle: "Forecasting yield and managing weather, market and operational risk.", minutes: 150, topics: ["risk"], audience: ["farm_manager", "advisor", "agronomist"] }),
  d({ id: "crs_d5", slug: "farm-operational-decision-making", program: "prg_d", sort: 5, title: "Farm Operational Decision-Making", subtitle: "Turning data and recommendations into daily operating decisions.", minutes: 120, topics: ["precision-agriculture"], audience: ["grower", "farm_manager", "operator"] }),
  d({ id: "crs_d6", slug: "agricultural-data-interpretation", program: "prg_d", sort: 6, title: "Agricultural Data Interpretation", subtitle: "Reading charts, maps and model outputs with a critical eye.", minutes: 120, topics: ["data"], audience: ["grower", "operator", "student"] }),
  // Program E
  d({ id: "crs_e1", slug: "agricultural-computer-vision", program: "prg_e", sort: 1, level: "advanced", title: "Agricultural Computer Vision", subtitle: "Detecting pests, disease, weeds and crop features in images.", minutes: 240, topics: ["computer-vision", "machine-learning"], audience: ["developer", "researcher", "student"] }),
  d({ id: "crs_e2", slug: "satellite-based-crop-analysis", program: "prg_e", sort: 2, level: "advanced", title: "Satellite-Based Crop Analysis", subtitle: "Time series, cloud masking and crop classification from orbit.", minutes: 240, topics: ["remote-sensing"], audience: ["researcher", "developer", "agronomist"] }),
  d({ id: "crs_e3", slug: "predictive-agricultural-analytics", program: "prg_e", sort: 3, level: "advanced", title: "Predictive Agricultural Analytics", subtitle: "Forecasting models, validation and uncertainty for agriculture.", minutes: 240, topics: ["machine-learning", "risk"], audience: ["researcher", "developer"] }),
  d({ id: "crs_e4", slug: "ai-agents-for-agriculture", program: "prg_e", sort: 4, level: "advanced", title: "AI Agents for Agriculture", subtitle: "Language-model agents, tools and guardrails for agricultural work.", minutes: 180, topics: ["agents"], audience: ["developer", "researcher"] }),
  d({ id: "crs_e5", slug: "agricultural-robotics", program: "prg_e", sort: 5, level: "advanced", title: "Agricultural Robotics", subtitle: "Perception, autonomy and safety for field robots.", minutes: 180, topics: ["robotics", "computer-vision"], audience: ["developer", "researcher", "student"] }),
  d({ id: "crs_e6", slug: "applied-agricultural-ai-case-studies", program: "prg_e", sort: 6, level: "advanced", title: "Applied Agricultural AI Case Studies", subtitle: "Lessons from real deployments: what worked, what didn't, and why.", minutes: 180, topics: ["ai-foundations"], audience: ["farm_manager", "researcher", "advisor", "developer"] }),
];

export const PATHS = [
  { id: "pth_grower", slug: "for-growers", role: "grower", title: "For farmers and growers", summary: "Understand what AI can do for your fields, your water and your margins — and how to keep the final say.", courses: ["crs_a1", "crs_d5", "crs_d1", "crs_d3", "crs_a6"] },
  { id: "pth_agronomist", slug: "for-agronomists", role: "agronomist", title: "For agronomists and advisors", summary: "Evaluate models, interpret imagery and give clients confident, evidence-based recommendations.", courses: ["crs_a1", "crs_a2", "crs_a4", "crs_a5", "crs_d3", "crs_d6"] },
  { id: "pth_manager", slug: "for-farm-managers", role: "farm_manager", title: "For farm and agribusiness managers", summary: "Lead AI adoption across teams: decisions, risk, water and verified results.", courses: ["crs_a1", "crs_b1", "crs_b4", "crs_d4", "crs_d2", "crs_b10"] },
  { id: "pth_operator", slug: "for-field-operators", role: "operator", title: "For field operators and technicians", summary: "Use AGRO-AI recommendations confidently in the daily routine of the operation.", courses: ["crs_a1", "crs_b2", "crs_b3", "crs_b4", "crs_d1"] },
  { id: "pth_student", slug: "for-students-and-researchers", role: "student", title: "For students and researchers", summary: "A rigorous route from AI fundamentals to remote sensing, machine learning and predictive analytics.", courses: ["crs_a1", "crs_a2", "crs_a3", "crs_a4", "crs_e2", "crs_e3"] },
  { id: "pth_developer", slug: "for-developers", role: "developer", title: "For developers and integrators", summary: "Build reliable integrations with the AGRO-AI Platform API and modern agricultural AI systems.", courses: ["crs_a1", "crs_c1", "crs_c2", "crs_c3", "crs_c5", "crs_c6", "crs_e4"] },
];
