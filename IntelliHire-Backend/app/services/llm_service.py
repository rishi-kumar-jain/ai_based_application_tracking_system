
import json
import re
import html
import logging
from typing import Any
from functools import lru_cache

from fastapi import HTTPException
from openai import AzureOpenAI

from app.core.config import Settings


logger = logging.getLogger("__LLMService__")


# =============================================================================
# JD MARKET ENHANCEMENT PROMPT
# =============================================================================

JD_ENHANCEMENT_MARKET_PROMPT = """
You are an AI Hiring Intelligence Expert.

You will receive a structured Job Description JSON (parsed output).

Your task is to:
1. Clean and standardize the JD
2. Structure the data for hiring systems
3. Evaluate JD quality
4. Align the JD with market standards
5. Provide a market-based scoring and insights

Return ONLY valid JSON. No explanations.

================================================================================
INPUT
================================================================================
{parsed_jd}

================================================================================
OUTPUT FORMAT
================================================================================
{
  "title": string,
  "location": string | null,

  "experience": {
    "text": string | null,
    "min_years": number | null,
    "max_years": number | null
  },

  "role_summary": string,

  "responsibilities": string[],

  "mandatory_skills": {
    "technical": string[],
    "tools_frameworks": string[],
    "soft_skills": string[]
  },

  "good_to_have_skills": string[],

  "jd_quality_score": {
    "overall": number,
    "market_alignment_score": number,
    "breakdown": {
      "role_clarity": number,
      "skill_relevance": number,
      "experience_alignment": number,
      "responsibility_definition": number,
      "candidate_attractiveness": number
    }
  },

  "market_insights": {
    "role_demand": string,
    "salary_range_india": string,
    "market_fit": string,
    "risk_flags": string[]
  },

  "improvement_suggestions": string[]
}

================================================================================
RULES
================================================================================

1. DATA CLEANING
- Remove duplicates
- Standardize wording
- Keep meaning intact
- Do NOT remove important information

2. EXPERIENCE STRUCTURING
- Extract min_years and max_years from experience text
- If not possible, set null

3. RESPONSIBILITIES
- Convert into clear, action-based bullet points
- Each point max 15-20 words

4. SKILL CLASSIFICATION
Classify skills into:
- technical: core technical/domain skills
- tools_frameworks: tools, platforms, libraries, HRIS, systems
- soft_skills: communication, leadership, stakeholder management, problem-solving

5. NO HALLUCINATION
- Do NOT introduce new technologies not present in input
- Only refine and organize

6. JD QUALITY SCORING
Evaluate:
- role_clarity
- skill_relevance
- experience_alignment
- responsibility_definition
- candidate_attractiveness

7. MARKET INSIGHTS
Provide:
- role_demand: High, Medium, or Low
- salary_range_india: realistic range based on experience, seniority, and demand
- market_fit
- risk_flags

8. IMPROVEMENT SUGGESTIONS
Provide 3-5 actionable suggestions.

9. OUTPUT RULES
- Return valid JSON only
- No extra fields
- No explanation text
""".strip()


# =============================================================================
# RESUME PARSE SYSTEM PROMPT
# =============================================================================

RESUME_PARSE_SYSTEM_PROMPT = """
================================================================================
PRODUCTION-GRADE RESUME PARSER & ATS MATCH ENGINE v8.0
Enterprise Semantic Resume Evaluation | AI Competency Matching
================================================================================

SYSTEM ROLE:
You are a strict enterprise-grade ATS resume parsing and AI competency evaluation engine.

Your responsibility is to:
- parse resumes
- evaluate candidates against JD mandatory skills
- perform semantic skill matching
- infer behavioral and leadership competencies
- evaluate transferable technologies
- generate recruiter-grade evaluations
- produce deterministic ATS-compatible JSON output

Return ONLY valid JSON.
Do NOT include markdown, explanations, comments, or extra text.

================================================================================
CRITICAL OUTPUT CONTRACT
================================================================================

The JD mandatory skills provided in the input are the SINGLE SOURCE OF TRUTH.

You MUST:
- evaluate EACH JD mandatory skill independently
- copy each JD skill EXACTLY into skill_evaluations[].jd_skill
- decide whether the resume FULLY matches, PARTIALLY matches, or DOES NOT match it
- report this decision ONLY via skill_evaluations

You MUST NOT:
- split JD mandatory skills
- paraphrase JD mandatory skills
- rewrite JD mandatory skills
- output fragmented JD text
- invent mandatory skills
- hallucinate experience
- assume expertise without evidence

matched_skills MUST always be [].
missing_skills MUST always be [].
The backend will derive final matched and missing skills.

================================================================================
REQUIRED OUTPUT SCHEMA
================================================================================

{
  "full_name": string | null,
  "email": string | null,
  "phone": string | null,
  "extracted_skills": string[],
  "candidate_summary": string,
  "work_experience": any,
  "total_years_of_experience": string | null,
  "other_scores": {
    "experience": number,
    "responsibilities": number,
    "projects": number,
    "location": number,
    "certification": number,
    "education": number
  },
  "other_score_justifications": {
    "experience": string,
    "responsibilities": string,
    "projects": string,
    "location": string,
    "certification": string,
    "education": string
  },
  "skill_evaluations": [
    {
      "jd_skill": string,
      "skill_type": string,
      "match_status": "matched" | "partial" | "missing",
      "match_score": number,
      "evidence_confidence": "high" | "medium" | "low",
      "matched_evidence": string[],
      "missing_evidence": string[]
    }
  ],
  "matched_skills": [],
  "missing_skills": []
}

================================================================================
TOTAL EXPERIENCE EXTRACTION RULES
================================================================================

- total_years_of_experience represents candidate's total professional experience.
- If explicitly stated, use it directly.
- Examples:
  - "10+ years of experience"
  - "8 years experience"
  - "5.5 years of professional experience"
  - "over 12 years"
- Preserve plus sign if present, e.g. "10+ years".
- If no explicit total experience exists, infer from work history date ranges.
- Treat Present, Current, Till Date as current year.
- Do NOT use education year alone.
- If experience cannot be determined, return null.
- Do NOT return 0 unless resume clearly says no professional experience.

================================================================================
SKILL TYPE CLASSIFICATION
================================================================================

Classify each JD mandatory skill into one:
1. hard_technical
2. behavioral
3. leadership
4. domain
5. process
6. platform_or_tool

Examples:
- hard_technical: Java, Python, Selenium, SQL, API Testing
- behavioral: Communication, Stakeholder management, Collaboration
- leadership: Team leadership, Mentoring, Delivery ownership
- domain: Banking, Telecom, Healthcare, Insurance, IT Services
- process: Agile, Scrum, SDLC, Defect management
- platform_or_tool: AWS, Azure, Kubernetes, Jenkins, Workday, SuccessFactors

================================================================================
SEMANTIC MATCHING RULES
================================================================================

Evaluate:
- exact matches
- semantic matches
- contextual matches
- ecosystem matches
- inferred behavioral evidence
- leadership indicators
- production-level evidence

Behavioral and leadership skills MUST NOT rely only on exact keywords.
Use contextual evidence such as collaboration, reporting, meetings, sprint ceremonies,
client interaction, mentoring, ownership, reviews, escalation handling, and delivery management.

================================================================================
TRANSFERABILITY RULES
================================================================================

Evaluate adjacent and transferable technologies.

Examples:
- Selenium, Playwright, Cypress, WebdriverIO are related UI automation tools.
- AWS, Azure, and GCP are related cloud platforms.
- Jenkins, GitHub Actions, GitLab CI, Azure DevOps are related CI/CD tools.
- Docker and Podman are related containerization tools.
- Kubernetes, OpenShift, EKS, AKS are related orchestration ecosystems.

Exact production usage:
- matched, score 90-100

Strong adjacent transferable technology:
- partial, score 55-80

Moderate conceptual overlap:
- partial, score 35-60

No meaningful relationship:
- missing

================================================================================
AND / OR SEMANTIC RULES
================================================================================

AND semantics:
- ALL parts required for matched.
- Partial coverage means partial.

OR semantics:
- ANY one component sufficient for matched.

Examples:
"Experience with AWS or Azure or GCP" -> AWS alone can satisfy matched.
"Python, Perl, and Shell" -> all required for matched.

================================================================================
OTHER SCORES
================================================================================

All scores must be 0-100.

experience:
- seniority and relevance

responsibilities:
- alignment with JD expectations

projects:
- complexity and relevance

location:
- if JD has no location, score 100
- if candidate location is near JD location, score higher
- do not over-penalize remote mismatch

certification:
- certification relevance only

education:
- degree relevance to role

Do NOT inflate other_scores to compensate for missing mandatory skills.

================================================================================
DYNAMIC SCREENING WEIGHTAGE RULES
================================================================================

Input includes Dynamic Screening Weights.

Possible keys:
- experience
- responsibilities
- projects
- location
- certification
- education

candidate_summary must focus on:
- JD mandatory skills
- matched, partial, and missing skill evidence
- active dynamic weights where weight > 0
- active other score justifications

Do NOT focus on any factor whose dynamic weight is 0.

================================================================================
FINAL VALIDATION
================================================================================

Before returning:
- valid JSON
- skill_evaluations count == JD mandatory skills count
- each jd_skill is exact copy from JD
- matched_skills == []
- missing_skills == []
- scores are 0-100
- no fragmented JD skills
- no hallucinated evidence
- candidate_summary is JD-specific and evidence-based

Return ONLY valid JSON.
""".strip()


# =============================================================================
# JD ANALYZE PROMPT
# =============================================================================

JD_ANALYZE_IMPROVE_PROMPT = """
================================================================================
PRODUCTION-GRADE JD ANALYZER
================================================================================

SYSTEM ROLE:
You are an enterprise-grade Job Description analyzer for ATS systems.

Return ONLY valid JSON.

================================================================================
TASK
================================================================================

Analyze the structured job description JSON and return JD quality scoring.

================================================================================
OUTPUT FORMAT
================================================================================

{
  "jd_score": number,
  "score_breakdown": {
    "role_clarity": number,
    "responsibility_quality": number,
    "skills_completeness": number,
    "experience_definition": number,
    "structure_formatting": number,
    "market_alignment": number
  },
  "strengths": string[],
  "suggestions": string[]
}

================================================================================
SCORING RULES
================================================================================

score_breakdown max values:
- role_clarity: 20
- responsibility_quality: 20
- skills_completeness: 20
- experience_definition: 15
- structure_formatting: 15
- market_alignment: 10

jd_score must ideally equal the sum of breakdown scores.

================================================================================
RULES
================================================================================

- Do not hallucinate.
- Evaluate only based on given JD JSON.
- Return 3-5 strengths.
- Return 3-5 actionable suggestions.
- Return valid JSON only.
""".strip()


# =============================================================================
# JD PARSE SYSTEM PROMPT
# =============================================================================

JD_PARSE_SYSTEM_PROMPT = """
================================================================================
PRODUCTION-GRADE JD PARSER v7.1
Strict JSON Output | Accurate Mapping | Role-Level Experience Protection
================================================================================

SYSTEM ROLE:
You are an enterprise-grade Job Description parser for a modern ATS.

You receive extracted raw JD text.
Your job is to identify, classify, normalize, and structure the JD into strict JSON.

Return ONLY valid JSON.

================================================================================
OUTPUT FORMAT
================================================================================

Return exactly this JSON:

{
  "title": string | null,
  "location": string | null,
  "experience": string | null,
  "role_summary": string | null,
  "responsibilities": array of strings,
  "mandatory_skills": array of strings,
  "good_to_have_skills": array of strings,
  "qualifications": array of strings
}

Rules:
- No extra keys
- No missing keys
- Use null for missing string fields
- Use [] for missing array fields
- Return valid JSON only

================================================================================
ATOMIC ARRAY RULE
================================================================================

Applies to:
- responsibilities
- mandatory_skills
- good_to_have_skills
- qualifications

Each array item must represent ONE complete semantic unit.

Do NOT split items because they contain:
- commas
- parentheses
- brackets
- slashes
- grouped examples
- tool lists
- certification suffixes
- layer ranges

Correct:
"Network protocols (Layer 2, Layer 3, Layer 4-7)"
"REST API design, validation, authentication, and error handling"
"Docker, Kubernetes, and container orchestration"

Incorrect:
"Layer 2,"
"Layer 3,"
"and container orchestration"

================================================================================
FIELD EXTRACTION RULES
================================================================================

1. TITLE
- Extract only the title.
- Remove job codes, IDs, location suffixes, and department suffixes.


2. LOCATION
- Extract exactly as written.
- Preserve multiple locations.
- Do not infer remote/hybrid unless explicitly stated.

3. EXPERIENCE
- Extract ONLY overall role-level experience.
- Use header/metadata/experience section first.
- Preserve exact wording where possible.
- Never replace with skill-level experience.

Examples:
"Experience Required: 8-14 Years" -> "8-14 Years"
"Python: 3+ years" -> keep inside mandatory_skills only if skill-specific.

If multiple role-level ranges exist:
1. Prefer "Experience Required" or "Experience Range".
2. If both are present and differ slightly, choose broader official range.
3. Do not combine ranges.
4. Do not place non-selected range into mandatory_skills.
5. If narrower range has domain context, preserve only domain context as mandatory skill.

4. ROLE_SUMMARY
- Extract from About the Role, Job Summary, Position Summary, Job Overview, Overview.
- Clean lightly.
- Do not convert into bullets.

5. RESPONSIBILITIES
- Return complete responsibility statements.
- Preserve action and ownership meaning.
- Do not fragment grouped details.

6. MANDATORY_SKILLS
Extract only:
- role capabilities
- competencies
- domain knowledge
- tools
- platforms
- systems
- methodologies
- communication capabilities
- analytical capabilities
- leadership capabilities
- practical skills required to perform the role

MANDATORY_SKILLS must NOT include:
- overall role-level experience range
- degree requirements
- education requirements
- certifications
- licenses
- credentials

If a line contains "Experience Range", "Required Experience", "Years of Experience",
or role-level range such as "8-14 years", extract only the range into experience.

If the same line contains useful domain context, convert only the domain context into mandatory_skills.

Example:
Input:
"Experience Range: 8-14 years of post-qualification experience, with a significant portion dedicated exclusively to North American C&B management within an IT Services organization."

Output:
"experience": "8-14 years"
"mandatory_skills": [
  "North American C&B management within an IT Services organization"
]

Never place full role-level experience sentence inside mandatory_skills.

7 GOOD_TO_HAVE_SKILLS
- Extract explicit preferred/nice-to-have skills first.
- If missing, infer only logical role-aligned complementary skills.
- Do not hallucinate unrelated skills.
- Keep grouped items together.

8. QUALIFICATIONS
Extract explicit:
- education
- degrees
- academic background
- certifications
- credentials
- licenses
- institute requirements

Always classify lines starting with or containing:
- Education:
- Qualification:
- Degree:
- Academic Background:
- Certification:
- License:

as qualifications, not mandatory_skills.

Example:
"Education: MBA in HR, master's degree in Human Resources, Finance, or a related field from a reputable institute."

Output:
"qualifications": [
  "MBA in HR, master's degree in Human Resources, Finance, or a related field from a reputable institute."
]

================================================================================
REQUIRED EXPERIENCE & QUALIFICATIONS SECTION HANDLING
================================================================================

When a section is titled "Required Experience & Qualifications", do NOT put the
whole section into mandatory_skills.

Classify sub-lines by label:

- Education -> qualifications
- Experience Range -> experience
- Market Expertise -> mandatory_skills
- Technical & Analytical Skills -> mandatory_skills
- Communication -> mandatory_skills
- Certifications -> qualifications
- Licenses -> qualifications

================================================================================
STRICT REQUIREMENT CLASSIFICATION
================================================================================

Do not treat all requirements as mandatory_skills.

Classify by meaning:

1. Education, degree, certification, license, credential -> qualifications
2. Overall role-level years of experience -> experience
3. Domain expertise, tool expertise, analytical capability, stakeholder capability,
   communication capability, leadership capability -> mandatory_skills
4. Job duties, ownership areas, execution activities -> responsibilities

Never place a full role-level experience sentence inside mandatory_skills.

================================================================================
FIELD SYNONYMS
================================================================================

ROLE SUMMARY:
- About the Role
- Job Summary
- Role Overview
- Job Overview
- Position Summary
- Overview

RESPONSIBILITIES:
- Responsibilities
- Key Responsibilities
- Duties
- What You'll Do
- Accountabilities

MANDATORY SKILLS:
- Required Skills
- Mandatory Skills
- Must-Have Skills
- Core Skills
- Essential Skills
- Technical Requirements
- Requirements
- Must Have

GOOD-TO-HAVE SKILLS:
- Preferred Skills
- Nice-to-Have
- Good to Have
- Bonus Skills
- Desirable Skills
- Additional Skills
- Preferred Experience

QUALIFICATIONS:
- Qualifications
- Education
- Certifications
- Credentials
- Degree
- Licenses
- Educational Background

LOCATION:
- Location
- Work Location
- Job Location
- Based In
- Office Location

EXPERIENCE:
- Experience
- Years of Experience
- Required Experience
- Experience Required
- Experience Range
- Experience Level
- Overall Experience
- Minimum Experience

================================================================================
FALLBACK MODE
================================================================================

If the JD is unstructured or short:

1. TITLE:
- Look for "Hiring for X", "Role: X", "Opening for X", or prominent title.

2. LOCATION:
- Look for Location, Place, Work from, city names.

3. EXPERIENCE:
- Look for Exp, Experience, X-Y yrs, X+ years.

4. MANDATORY_SKILLS & GOOD_TO_HAVE_SKILLS:
- Identify technologies, tools, platforms, capabilities, competencies, and domain knowledge.
- Move certifications, degrees, licenses, credentials, and education requirements to qualifications.
- Preferred/nice-to-have items go to good_to_have_skills.
- Others go to mandatory_skills.

5. RESPONSIBILITIES:
- Create only if there are clear activity descriptions.

6. ROLE_SUMMARY:
- Use short introductory sentence if available.

7. QUALIFICATIONS:
- Extract only if explicitly stated.

================================================================================
FINAL VALIDATION
================================================================================

Before returning:
- JSON is valid
- Only allowed keys exist
- All required keys exist
- Experience is role-level only
- Skill-level years stay inside skills only if skill-specific
- No fragmented array items
- Qualifications are not in mandatory_skills
- Overall experience sentences are not in mandatory_skills

Return ONLY JSON.
""".strip()


# =============================================================================
# JD ENHANCER PROMPTS
# =============================================================================

ENHANCE_JD_USER_PROMPT_TEMPLATE = """
================================================================================
TASK
================================================================================

Enhance the following parsed job description into a polished, ATS-ready,
candidate-attracting JD.

Use parsed_jd as the main structured source.
Use original_jd_text as supporting context.

Do NOT perform extraction again from scratch.
Do NOT add unrelated information.
Do NOT copy-paste short parsed phrases as final output.

================================================================================
IMPORTANT FIELD BEHAVIOR
================================================================================

- experience:
  Keep null if no explicit role-level experience is present.
  Do not infer experience from title, grade, or seniority.

- role_summary:
  If null or weak, generate a professional 3-5 sentence summary from available context.

- responsibilities:
  Rewrite into strong, complete, action-oriented professional statements.
  If short or vague, expand slightly using only role context.

- mandatory_skills:
  Preserve true mandatory skills and role competencies.
  Enrich weak or generic skills into clearer ATS-friendly skill phrases.
  Preserve tools, domains, versions, protocols, grouped technologies, and scope details only when they are actual skills or competencies.
  Do NOT preserve overall role-level years of experience inside mandatory_skills.
  Do NOT preserve education requirements, degree requirements, certifications, licenses, or credentials inside mandatory_skills.
  Move role-level experience to experience.
  Move education/degrees/certifications/licenses/credentials to qualifications.
  Do not invent unrelated tools, platforms, certifications, domains, or technologies.

- good_to_have_skills:
  If empty, infer 3-6 logical role-aligned skills from context.
  Do not duplicate mandatory skills.

- jd_score:
  Always return number from 0 to 100.

- jd_score_justification:
  Always return non-empty justification.

- suggestions:
  Always return 3-5 useful improvement suggestions.

================================================================================
PARSED JD
================================================================================

{parsed_jd_json}

================================================================================
ORIGINAL JD TEXT
================================================================================

{raw_text}

================================================================================
OUTPUT
================================================================================

Return ONLY valid JSON with exactly these keys:

{{
  "title": string | null,
  "location": string | null,
  "experience": string | null,
  "role_summary": string,
  "responsibilities": string[],
  "mandatory_skills": string[],
  "good_to_have_skills": string[],
  "qualifications": string[],
  "jd_score": number,
  "jd_score_justification": string | null,
  "suggestions": string[]
}}
""".strip()


JD_ENHANCER_SYSTEM_PROMPT = """
================================================================================
PRODUCTION-GRADE JD ENHANCER v8.1
General Role-Aware Enhancement | Contextual Inference | ATS-Ready Output
================================================================================

SYSTEM ROLE:
You are a senior technical recruiter, hiring-content specialist, and ATS optimization expert.

You receive:
1. parsed_jd: structured JD JSON
2. original_jd_text: raw extracted JD text

Your task is to transform parsed_jd into a polished, recruiter-ready,
candidate-attracting, ATS-ready job description.

Return ONLY valid JSON.

================================================================================
STRICT OUTPUT FORMAT
================================================================================

{
  "title": string | null,
  "location": string | null,
  "experience": string | null,
  "role_summary": string,
  "responsibilities": string[],
  "mandatory_skills": string[],
  "good_to_have_skills": string[],
  "qualifications": string[],
  "jd_score": number,
  "jd_score_justification": string | null,
  "suggestions": string[]
}

No extra keys.
No missing keys.

================================================================================
FIELD RULES
================================================================================

1. TITLE
- Preserve original title.
- Clean formatting only.


2. LOCATION
- Preserve original location.
- Do not invent.

3. EXPERIENCE
- Preserve explicit role-level experience only.
- Do not infer from title, grade, or seniority.
- Do not use skill-level experience as overall experience.

4. ROLE_SUMMARY
- Must not be empty if title/responsibilities/skills exist.
- Write 3-5 professional sentences.
- Include role purpose, work area, skills/domain, collaboration, impact.
- Do not invent company claims.

5. RESPONSIBILITIES
- Rewrite into clear, action-oriented statements.
- Use verbs like Design, Lead, Manage, Drive, Collaborate, Analyze, Optimize.
- If fewer than 6 responsibilities, expand to 6-8 logical responsibilities if supported.
- Do not add unrelated responsibilities.

6. MANDATORY_SKILLS
- Preserve true mandatory skill and competency meanings.
- Enrich only as needed for clarity and ATS value.
- Keep tools, versions, grouped skills, OR/AND logic, domains, protocols, and scope details only when they are true skill details.
- Do NOT keep overall role-level years of experience inside mandatory_skills.
- Do NOT keep degrees, education requirements, certifications, licenses, or credentials inside mandatory_skills.
- Move overall role-level experience to experience.
- Move education, degrees, certifications, licenses, and credentials to qualifications.
- Avoid duplicates.
- Do not invent unsupported technologies.

If an item contains overall role-level years of experience:
- Move range to experience.
- Preserve only useful domain context as mandatory skill if applicable.

If an item contains education, degree, certification, license, or credential:
- Move it to qualifications.

7. GOOD_TO_HAVE_SKILLS
- If explicit good-to-have skills exist, enhance them.
- If missing, infer 3-6 logical complementary role-aligned skills.
- Do not duplicate mandatory skills.
- Do not add unrelated tools or certifications.

8. QUALIFICATIONS
- Preserve explicit degrees, education, certifications, licenses, credentials.
- Preserve specific degree names like MBA, B.Tech, B.E, M.Tech, MCA, PhD.
- Do not duplicate qualification meaning.

9. JD_SCORE
Return number 0-100.

Score based on:
- completeness
- role summary clarity
- responsibility strength
- mandatory skill specificity
- good-to-have usefulness
- experience clarity
- candidate attractiveness

10. JD_SCORE_JUSTIFICATION
- Non-empty.
- Within 150 words.
- Explain deductions and weak areas.
- If score below 90, mention main gaps.

11. SUGGESTIONS
Return 3-5 actionable suggestions.

================================================================================
STRICT REQUIREMENT CLASSIFICATION
================================================================================

Do not treat all requirements as mandatory_skills.

Classify by meaning:
1. Education, degree, academic background, certification, license, credential -> qualifications
2. Overall role-level years of experience -> experience
3. Domain expertise, tool expertise, platform expertise, analytical capability,
   communication capability, stakeholder capability, leadership capability -> mandatory_skills
4. Duties, ownership areas, delivery accountabilities -> responsibilities

If section is "Required Experience & Qualifications":
- Education -> qualifications
- Experience Range -> experience
- Market Expertise -> mandatory_skills
- Technical & Analytical Skills -> mandatory_skills
- Communication -> mandatory_skills

Never place full role-level experience sentence inside mandatory_skills.

================================================================================
FINAL VALIDATION
================================================================================

Before returning:
- valid JSON
- all required keys
- no extra keys
- mandatory_skills does not contain role-level experience range
- mandatory_skills does not contain degrees/certifications/licenses/education
- qualifications captures explicit education and certifications
- no fragmented arrays
- jd_score numeric
- jd_score_justification non-empty
- suggestions present

Return ONLY JSON.
""".strip()


# =============================================================================
# AZURE CLIENT
# =============================================================================

@lru_cache(maxsize=1)
def _azure_client(api_key: str, api_version: str, endpoint: str) -> AzureOpenAI:
    return AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    )


# =============================================================================
# BASIC HELPERS
# =============================================================================

def _strip_json_fence(content: str) -> str:
    content = content.strip()

    if content.startswith("```"):
        content = content.strip("`")
        lines = content.splitlines()

        if lines and lines[0].lower().startswith("json"):
            lines = lines[1:]

        content = "\n".join(lines)

    return content.strip()


def _safe_str(v: Any) -> str | None:
    if v is None:
        return None

    s = html.unescape(str(v)).strip()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s)

    return s if s else None


def _clean_str_value(value: Any) -> str | None:
    return _safe_str(value)


def _safe_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    result = []

    for item in value:
        text = _clean_str_value(item)
        if text:
            result.append(text)

    return result


def _clean_list_value(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    result = []
    seen = set()

    for item in value:
        text = _clean_str_value(item)
        if not text:
            continue

        key = text.lower()

        if key not in seen:
            result.append(text)
            seen.add(key)

    return result


# =============================================================================
# JD PREPROCESSING + NORMALIZATION
# =============================================================================

ROLE_EXPERIENCE_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?\s*(?:-|–|—|to)\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\+?)\s*(?:years|year|yrs|yr)\b",
    re.IGNORECASE,
)

EXPERIENCE_LABEL_PATTERN = re.compile(
    r"\b("
    r"experience range|"
    r"required experience|"
    r"experience required|"
    r"years of experience|"
    r"overall experience|"
    r"minimum experience|"
    r"total experience"
    r")\b",
    re.IGNORECASE,
)

QUALIFICATION_PATTERN = re.compile(
    r"\b("
    r"MBA|BBA|B\.?Tech|B\.?E\.?|M\.?Tech|MCA|BCA|Ph\.?D|"
    r"master'?s degree|bachelor'?s degree|degree|diploma|"
    r"education|academic background|qualification|qualifications|"
    r"certification|certified|license|licence|credential|credentials"
    r")\b",
    re.IGNORECASE,
)


def preprocess_jd_text(text: str) -> str:
    """
    Cleans extracted JD text before sending it to the LLM.
    Fixes HTML entities, compact labels, and inconsistent dashes.
    """
    if not text:
        return ""

    text = html.unescape(text)
    text = text.replace("–", "-").replace("—", "-")

    labels = [
        "Job Title:",
        "Location:",
        "Experience Required:",
        "Employment Type:",
        "Education:",
        "Experience Range:",
        "Market Expertise:",
        "Technical & Analytical Skills:",
        "Technical and Analytical Skills:",
        "Communication:",
        "Role:",
        "Experience:",
        "Industry Preference:",
        "Required Experience & Qualifications",
        "Required Experience and Qualifications",
        "Key Responsibilities:",
        "Overview of the Role:",
        "Why Join Us",
    ]

    for label in labels:
        text = text.replace(label, f"\n{label}")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def extract_experience_range(text: str) -> str | None:
    if not text:
        return None

    text = html.unescape(str(text))
    text = text.replace("–", "-").replace("—", "-")

    patterns = [
        r"\b\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*(?:years|year|yrs|yr)\b",
        r"\b\d+(?:\.\d+)?\s+to\s+\d+(?:\.\d+)?\s*(?:years|year|yrs|yr)\b",
        r"\b\d+(?:\.\d+)?\+?\s*(?:years|year|yrs|yr)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip()

    return None


def strip_experience_from_skill(text: str) -> str | None:
    """
    Converts an incorrectly classified role-level experience sentence into domain context.

    Example:
    '8-14 years of post-qualification experience, with significant focus on North American C&B management'
    -> 'North American C&B management'
    """
    if not text:
        return None

    original = html.unescape(str(text)).strip()
    text = original.replace("–", "-").replace("—", "-")

    text = re.sub(
        r"^\s*(experience range|required experience|experience required|years of experience|overall experience|minimum experience|total experience)\s*:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = ROLE_EXPERIENCE_PATTERN.sub("", text)

    cleanup_patterns = [
        r"\bof post-qualification experience\b",
        r"\bpost-qualification experience\b",
        r"\bof experience\b",
        r"\bexperience\b",
        r"\bwith a significant portion dedicated exclusively to\b",
        r"\bwith significant portion dedicated exclusively to\b",
        r"\bwith a substantial portion dedicated exclusively to\b",
        r"\bwith substantial portion dedicated exclusively to\b",
        r"\bwith a significant portion dedicated to\b",
        r"\bwith significant portion dedicated to\b",
        r"\bwith a substantial portion dedicated to\b",
        r"\bwith substantial portion dedicated to\b",
        r"\bwith a significant focus on\b",
        r"\bwith significant focus on\b",
        r"\bwith a substantial focus on\b",
        r"\bwith substantial focus on\b",
        r"\bdedicated exclusively to\b",
        r"\bdedicated to\b",
    ]

    for pattern in cleanup_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    text = re.sub(r"^[,:\-\s]+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .,-")

    if not text:
        return None

    if text.lower() == original.lower():
        return None

    if ROLE_EXPERIENCE_PATTERN.search(text):
        return None

    if len(text.split()) < 3:
        return None

    return text


def normalize_jd_classification(jd: dict) -> dict:
    """
    Deterministic safety layer for JD parsing/enhancement.

    Guarantees:
    - Role-level experience does not remain in mandatory_skills.
    - Degrees/certifications/licenses/education move to qualifications.
    - HTML entities are decoded.
    - Duplicate list values are removed.
    """
    if not isinstance(jd, dict):
        jd = {}

    normalized = {
        "title": _clean_str_value(jd.get("title")),
        "location": _clean_str_value(jd.get("location")),
        "experience": _clean_str_value(jd.get("experience")),
        "role_summary": _clean_str_value(jd.get("role_summary")),
        "responsibilities": _clean_list_value(jd.get("responsibilities")),
        "mandatory_skills": _clean_list_value(jd.get("mandatory_skills")),
        "good_to_have_skills": _clean_list_value(jd.get("good_to_have_skills")),
        "qualifications": _clean_list_value(jd.get("qualifications")),
    }

    if "jd_score" in jd:
        normalized["jd_score"] = jd.get("jd_score")

    if "jd_score_justification" in jd:
        normalized["jd_score_justification"] = _clean_str_value(
            jd.get("jd_score_justification")
        )

    if "suggestions" in jd:
        normalized["suggestions"] = _clean_list_value(jd.get("suggestions"))

    new_mandatory_skills = []
    qualifications = normalized["qualifications"]

    for item in normalized["mandatory_skills"]:
        text = _clean_str_value(item)

        if not text:
            continue

        is_qualification = bool(QUALIFICATION_PATTERN.search(text))
        has_experience_range = bool(ROLE_EXPERIENCE_PATTERN.search(text))
        has_experience_label = bool(EXPERIENCE_LABEL_PATTERN.search(text))

        if is_qualification:
            if text not in qualifications:
                qualifications.append(text)
            continue

        if has_experience_range or has_experience_label:
            extracted_experience = extract_experience_range(text)

            if extracted_experience and not normalized.get("experience"):
                normalized["experience"] = extracted_experience

            domain_skill = strip_experience_from_skill(text)

            if domain_skill:
                new_mandatory_skills.append(domain_skill)

            continue

        new_mandatory_skills.append(text)

    normalized["mandatory_skills"] = _clean_list_value(new_mandatory_skills)
    normalized["qualifications"] = _clean_list_value(qualifications)

    if normalized.get("experience"):
        normalized["experience"] = _clean_str_value(normalized["experience"])

    return normalized


# =============================================================================
# JD PARSING / ENHANCEMENT
# =============================================================================

def parse_and_enhance_jd(settings: Settings, text: str) -> dict:
    text = preprocess_jd_text(text)

    parsed = parse_jd_with_llm(settings, text)
    parsed = normalize_jd_classification(parsed)

    enhanced = enhance_jd_with_llm(settings, parsed, text)
    enhanced = normalize_jd_classification(enhanced)

    return enhanced


def parse_jd_with_llm(settings: Settings, text: str) -> dict:
    if settings.llm_provider == "mock":
        return normalize_jd_classification(
            {
                "title": "Parsed Title",
                "department": "Engineering",
                "location": "Remote",
                "experience": "3+ years",
                "role_summary": "Auto-parsed summary",
                "responsibilities": ["Design APIs", "Review code"],
                "mandatory_skills": ["Python", "FastAPI"],
                "good_to_have_skills": ["AWS", "Docker"],
                "qualifications": ["mock"],
            }
        )

    if settings.llm_provider != "azure":
        raise HTTPException(status_code=500, detail="Unsupported LLM provider")

    text = preprocess_jd_text(text)
    prompt = f"Job Description Text:\n{text}"

    client = _azure_client(
        settings.azure_openai_api_key,
        settings.azure_openai_api_version,
        settings.azure_openai_endpoint,
    )

    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": JD_PARSE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(_strip_json_fence(content))

    parsed["title"] = _safe_str(parsed.get("title"))
    parsed["location"] = _safe_str(parsed.get("location"))
    parsed["experience"] = _safe_str(parsed.get("experience"))
    parsed["role_summary"] = _safe_str(parsed.get("role_summary"))

    parsed["responsibilities"] = _safe_list(parsed.get("responsibilities"))
    parsed["mandatory_skills"] = _safe_list(parsed.get("mandatory_skills"))
    parsed["good_to_have_skills"] = _safe_list(parsed.get("good_to_have_skills"))
    parsed["qualifications"] = _safe_list(parsed.get("qualifications"))

    return normalize_jd_classification(parsed)


def enhance_jd_with_llm(settings: Settings, parsed: dict, raw_text: str) -> dict:
    parsed = normalize_jd_classification(parsed)
    raw_text = preprocess_jd_text(raw_text)

    client = _azure_client(
        settings.azure_openai_api_key,
        settings.azure_openai_api_version,
        settings.azure_openai_endpoint,
    )

    prompt = ENHANCE_JD_USER_PROMPT_TEMPLATE.format(
        parsed_jd_json=json.dumps(parsed, ensure_ascii=False, indent=2),
        raw_text=raw_text,
    )

    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        temperature=0.25,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": JD_ENHANCER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    content = response.choices[0].message.content or "{}"
    enhanced = json.loads(_strip_json_fence(content))
    enhanced = normalize_jd_classification(enhanced)

    return _safety_merge_enhanced(enhanced, parsed)


def _safety_merge_enhanced(enhanced: dict, parsed: dict) -> dict:
    """
    Keep enhanced output whenever available.
    Fall back to parsed values only when enhanced fields are missing.
    Final output is normalized so role-level experience and qualifications
    cannot leak into mandatory_skills.
    """
    if not isinstance(enhanced, dict):
        enhanced = {}

    if not isinstance(parsed, dict):
        parsed = {}

    result = {}

    result["title"] = enhanced.get("title") or parsed.get("title")
    result["location"] = enhanced.get("location") or parsed.get("location")

    result["experience"] = parsed.get("experience") or enhanced.get("experience")
    result["role_summary"] = enhanced.get("role_summary") or parsed.get("role_summary")

    result["responsibilities"] = (
        enhanced.get("responsibilities")
        if isinstance(enhanced.get("responsibilities"), list)
        and enhanced.get("responsibilities")
        else parsed.get("responsibilities") or []
    )

    result["mandatory_skills"] = (
        enhanced.get("mandatory_skills")
        if isinstance(enhanced.get("mandatory_skills"), list)
        and enhanced.get("mandatory_skills")
        else parsed.get("mandatory_skills") or []
    )

    result["good_to_have_skills"] = (
        enhanced.get("good_to_have_skills")
        if isinstance(enhanced.get("good_to_have_skills"), list)
        and enhanced.get("good_to_have_skills")
        else parsed.get("good_to_have_skills") or []
    )

    result["qualifications"] = (
        enhanced.get("qualifications")
        if isinstance(enhanced.get("qualifications"), list)
        and enhanced.get("qualifications")
        else parsed.get("qualifications") or []
    )

    try:
        result["jd_score"] = int(float(enhanced.get("jd_score")))
    except Exception:
        result["jd_score"] = 0

    suggestions = enhanced.get("suggestions")
    result["suggestions"] = suggestions if isinstance(suggestions, list) else []

    jd_score_justification = enhanced.get("jd_score_justification")

    result["jd_score_justification"] = (
        jd_score_justification
        if isinstance(jd_score_justification, str)
        and jd_score_justification.strip()
        else (
            "The JD score reflects the completeness of key fields, clarity of responsibilities, "
            "specificity of skills, availability of experience information, and overall candidate attractiveness."
        )
    )

    return normalize_jd_classification(result)


def is_valid_parsed_output(parsed: dict) -> bool:
    if not parsed:
        return False

    score = 0

    if parsed.get("title"):
        score += 1
    if parsed.get("role_summary"):
        score += 1
    if parsed.get("mandatory_skills"):
        score += 1
    if parsed.get("responsibilities"):
        score += 1

    return score >= 2


# =============================================================================
# JD ANALYSIS
# =============================================================================

def analyze_jd_with_llm(settings: Settings, jd_payload: dict) -> dict:
    if settings.llm_provider == "mock":
        return {
            "jd_score": 78,
            "score_breakdown": {
                "role_clarity": 16,
                "responsibility_quality": 15,
                "skills_completeness": 16,
                "experience_definition": 12,
                "structure_formatting": 11,
                "market_alignment": 8,
            },
            "strengths": [
                "Role title and core purpose are clearly defined",
                "Mandatory skills are relevant to the role",
                "Responsibilities are reasonably actionable",
            ],
            "suggestions": [
                "Clarify business impact in the role summary",
                "Add more measurable responsibilities to improve clarity",
                "Expand good-to-have skills to improve candidate attraction",
            ],
        }

    if settings.llm_provider != "azure":
        raise HTTPException(status_code=500, detail="Unsupported LLM provider")

    client = _azure_client(
        settings.azure_openai_api_key,
        settings.azure_openai_api_version,
        settings.azure_openai_endpoint,
    )

    prompt = f"""
Analyze the following structured job description JSON and return JD quality scoring output.

Structured JD JSON:
{json.dumps(jd_payload, ensure_ascii=False, indent=2)}
""".strip()

    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": JD_ANALYZE_IMPROVE_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(_strip_json_fence(content))

    return normalize_jd_analysis_response(parsed)


def _clamp_number(value: Any, minimum: int, maximum: int) -> int:
    try:
        v = float(value)
    except Exception:
        v = float(minimum)

    v = max(minimum, min(maximum, v))

    return int(round(v))


def _safe_analysis_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    result = []

    for item in value:
        s = str(item).strip()
        if s:
            result.append(s)

    return result


def normalize_jd_analysis_response(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raw = {}

    breakdown = raw.get("score_breakdown", {}) or {}

    if not isinstance(breakdown, dict):
        breakdown = {}

    normalized_breakdown = {
        "role_clarity": _clamp_number(breakdown.get("role_clarity", 0), 0, 20),
        "responsibility_quality": _clamp_number(
            breakdown.get("responsibility_quality", 0), 0, 20
        ),
        "skills_completeness": _clamp_number(
            breakdown.get("skills_completeness", 0), 0, 20
        ),
        "experience_definition": _clamp_number(
            breakdown.get("experience_definition", 0), 0, 15
        ),
        "structure_formatting": _clamp_number(
            breakdown.get("structure_formatting", 0), 0, 15
        ),
        "market_alignment": _clamp_number(
            breakdown.get("market_alignment", 0), 0, 10
        ),
    }

    total_score = sum(normalized_breakdown.values())

    return {
        "jd_score": total_score,
        "score_breakdown": normalized_breakdown,
        "strengths": _safe_analysis_list(raw.get("strengths", []))[:5],
        "suggestions": _safe_analysis_list(raw.get("suggestions", []))[:5],
    }


# =============================================================================
# RESUME EVALUATION
# =============================================================================

def evaluate_resume_with_llm(
    settings: Settings,
    jd_dict: dict,
    resume_text: str,
    screening_weights: dict | None = None,
) -> dict:
    jd_dict = normalize_jd_classification(jd_dict) if isinstance(jd_dict, dict) else jd_dict

    if settings.llm_provider == "mock":
        mandatory = jd_dict.get("mandatory_skills") or []

        return normalize_resume_llm_output(
            {
                "full_name": "Mock Candidate",
                "email": "mock@example.com",
                "phone": None,
                "extracted_skills": ["Java", "SQL", "Communication"],
                "candidate_summary": "Mock candidate summary",
                "work_experience": [],
                "total_years_of_experience": "3+ years",
                "other_scores": {
                    "experience": 80,
                    "responsibilities": 75,
                    "projects": 78,
                    "location": 90,
                    "certification": 60,
                    "education": 85,
                },
                "other_score_justifications": {
                    "experience": "Mock experience justification.",
                    "responsibilities": "Mock responsibilities justification.",
                    "projects": "Mock projects justification.",
                    "location": "Mock location justification.",
                    "certification": "Mock certification justification.",
                    "education": "Mock education justification.",
                },
                "skill_evaluations": [
                    {
                        "jd_skill": skill,
                        "skill_type": "hard_technical",
                        "match_status": "matched"
                        if i < max(0, len(mandatory) - 1)
                        else "missing",
                        "match_score": 100
                        if i < max(0, len(mandatory) - 1)
                        else 0,
                        "evidence_confidence": "medium",
                        "matched_evidence": [],
                        "missing_evidence": [],
                    }
                    for i, skill in enumerate(mandatory)
                ],
                "matched_skills": [],
                "missing_skills": [],
            },
            mandatory,
        )

    if settings.llm_provider != "azure":
        raise HTTPException(status_code=500, detail="Unsupported LLM provider")

    effective_screening_weights = screening_weights or settings.screening_weights

    prompt = f"""
Job Description Context:
{json.dumps(jd_dict, ensure_ascii=False)}

Dynamic Screening Weights:
{json.dumps(effective_screening_weights, ensure_ascii=False)}

Resume Text:
{resume_text}
""".strip()

    client = _azure_client(
        settings.azure_openai_api_key,
        settings.azure_openai_api_version,
        settings.azure_openai_endpoint,
    )

    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": RESUME_PARSE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(_strip_json_fence(content))

    return normalize_resume_llm_output(parsed, jd_dict.get("mandatory_skills") or [])


def _safe_list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    result = []

    for item in value:
        s = _clean_str_value(item)
        if s:
            result.append(s)

    return result


def _safe_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


# def _safe_score_0_100(value: Any) -> float:
#     try:
#         v = float(value)
#     except Exception:
#         v = 0.0

#     v = max(0.0, min(100.0, v))

#     return round(v, 2)


# def _normalize_match_status(value: Any) -> str:
#     s = str(value or "").strip().lower()

#     if s == "matched":
#         return "matched"

#     if s == "partial":
#         return "partial"

#     return "missing"


# def normalize_resume_llm_output(
#     llm_result: dict,
#     jd_mandatory_skills: list[str],
# ) -> dict:
#     jd_mandatory_skills = [
#         str(x).strip()
#         for x in (jd_mandatory_skills or [])
#         if str(x).strip()
#     ]

#     llm_result = llm_result if isinstance(llm_result, dict) else {}

#     llm_result["full_name"] = _clean_str_value(llm_result.get("full_name"))
#     llm_result["email"] = _clean_str_value(llm_result.get("email"))
#     llm_result["phone"] = _clean_str_value(llm_result.get("phone"))
#     llm_result["extracted_skills"] = _safe_list_of_strings(
#         llm_result.get("extracted_skills")
#     )
#     llm_result["candidate_summary"] = (
#         _clean_str_value(llm_result.get("candidate_summary")) or ""
#     )
#     llm_result["work_experience"] = llm_result.get("work_experience")
#     llm_result["total_years_of_experience"] = _clean_str_value(
#         llm_result.get("total_years_of_experience")
#     )

#     other_scores = _safe_dict(llm_result.get("other_scores"))

#     llm_result["other_scores"] = {
#         "experience": _safe_score_0_100(other_scores.get("experience", 0)),
#         "responsibilities": _safe_score_0_100(
#             other_scores.get("responsibilities", 0)
#         ),
#         "projects": _safe_score_0_100(other_scores.get("projects", 0)),
#         "location": _safe_score_0_100(other_scores.get("location", 0)),
#         "certification": _safe_score_0_100(
#             other_scores.get("certification", 0)
#         ),
#         "education": _safe_score_0_100(other_scores.get("education", 0)),
#     }

#     other_justifications = _safe_dict(
#         llm_result.get("other_score_justifications")
#     )

#     llm_result["other_score_justifications"] = {
#         "experience": _clean_str_value(other_justifications.get("experience"))
#         or "Experience evidence is missing or weak.",
#         "responsibilities": _clean_str_value(
#             other_justifications.get("responsibilities")
#         )
#         or "Responsibility evidence is missing or weak.",
#         "projects": _clean_str_value(other_justifications.get("projects"))
#         or "Project evidence is missing or weak.",
#         "location": _clean_str_value(other_justifications.get("location"))
#         or "Location evidence is missing or not applicable.",
#         "certification": _clean_str_value(
#             other_justifications.get("certification")
#         )
#         or "Certification evidence is missing or weak.",
#         "education": _clean_str_value(other_justifications.get("education"))
#         or "Education evidence is missing or weak.",
#     }

#     raw_evals = llm_result.get("skill_evaluations")
#     raw_evals = raw_evals if isinstance(raw_evals, list) else []

#     eval_map = {}

#     for item in raw_evals:
#         if not isinstance(item, dict):
#             continue

#         jd_skill = str(item.get("jd_skill") or "").strip()

#         if jd_skill not in jd_mandatory_skills:
#             continue

#         eval_map[jd_skill] = {
#             "jd_skill": jd_skill,
#             "skill_type": _clean_str_value(item.get("skill_type"))
#             or "hard_technical",
#             "match_status": _normalize_match_status(item.get("match_status")),
#             "match_score": _safe_score_0_100(item.get("match_score", 0)),
#             "evidence_confidence": _clean_str_value(
#                 item.get("evidence_confidence")
#             )
#             or "low",
#             "matched_evidence": _safe_list_of_strings(
#                 item.get("matched_evidence")
#             ),
#             "missing_evidence": _safe_list_of_strings(
#                 item.get("missing_evidence")
#             ),
#         }

#     skill_evaluations = []
#     matched_skills = []
#     partial_skills = []
#     missing_skills = []
#     total_skill_score = 0.0

#     for jd_skill in jd_mandatory_skills:
#         if jd_skill in eval_map:
#             ev = eval_map[jd_skill]
#         else:
#             ev = {
#                 "jd_skill": jd_skill,
#                 "skill_type": "hard_technical",
#                 "match_status": "missing",
#                 "match_score": 0.0,
#                 "evidence_confidence": "low",
#                 "matched_evidence": [],
#                 "missing_evidence": [],
#             }

#         skill_evaluations.append(ev)
#         total_skill_score += ev["match_score"]

#         status = ev["match_status"]

#         if status == "matched":
#             matched_skills.append(jd_skill)
#         elif status == "partial":
#             partial_skills.append(jd_skill)
#         else:
#             missing_skills.append(jd_skill)

#     llm_result["skill_evaluations"] = skill_evaluations
#     llm_result["matched_skills"] = matched_skills
#     llm_result["partial_skills"] = partial_skills
#     llm_result["skills_partial"] = len(partial_skills)
#     llm_result["missing_skills"] = missing_skills
#     llm_result["skills_matched"] = len(matched_skills)
#     llm_result["total_skills"] = len(jd_mandatory_skills)
#     llm_result["skill_score"] = (
#         round(total_skill_score / len(jd_mandatory_skills), 2)
#         if jd_mandatory_skills
#         else 0.0
#     )

#     return llm_result


PARTIAL_MIN = 35.0
PARTIAL_MAX = 80.0


def _safe_score_0_100(value: Any) -> float:
    try:
        v = float(value)
    except Exception:
        v = 0.0

    v = max(0.0, min(100.0, v))

    return round(v, 2)


def _normalize_match_status(value: Any) -> str:
    s = str(value or "").strip().lower()

    if s == "matched":
        return "matched"

    if s == "partial":
        return "partial"

    return "missing"


def _credit_for_evaluation(ev: dict) -> float:
    """
    Deterministic skill credit derived from match_status:
      matched -> 100 (full credit, regardless of LLM's raw score)
      partial -> LLM's match_score clamped into [PARTIAL_MIN, PARTIAL_MAX]
      missing -> 0
    """
    status = ev.get("match_status")

    if status == "matched":
        return 100.0

    if status == "partial":
        raw = float(ev.get("match_score") or 0.0)
        return round(min(max(raw, PARTIAL_MIN), PARTIAL_MAX), 2)

    return 0.0


def normalize_resume_llm_output(
    llm_result: dict,
    jd_mandatory_skills: list[str],
) -> dict:
    jd_mandatory_skills = [
        str(x).strip()
        for x in (jd_mandatory_skills or [])
        if str(x).strip()
    ]

    llm_result = llm_result if isinstance(llm_result, dict) else {}

    llm_result["full_name"] = _clean_str_value(llm_result.get("full_name"))
    llm_result["email"] = _clean_str_value(llm_result.get("email"))
    llm_result["phone"] = _clean_str_value(llm_result.get("phone"))
    llm_result["extracted_skills"] = _safe_list_of_strings(
        llm_result.get("extracted_skills")
    )
    llm_result["candidate_summary"] = (
        _clean_str_value(llm_result.get("candidate_summary")) or ""
    )
    llm_result["work_experience"] = llm_result.get("work_experience")
    llm_result["total_years_of_experience"] = _clean_str_value(
        llm_result.get("total_years_of_experience")
    )

    other_scores = _safe_dict(llm_result.get("other_scores"))

    llm_result["other_scores"] = {
        "experience": _safe_score_0_100(other_scores.get("experience", 0)),
        "responsibilities": _safe_score_0_100(
            other_scores.get("responsibilities", 0)
        ),
        "projects": _safe_score_0_100(other_scores.get("projects", 0)),
        "location": _safe_score_0_100(other_scores.get("location", 0)),
        "certification": _safe_score_0_100(
            other_scores.get("certification", 0)
        ),
        "education": _safe_score_0_100(other_scores.get("education", 0)),
    }

    other_justifications = _safe_dict(
        llm_result.get("other_score_justifications")
    )

    llm_result["other_score_justifications"] = {
        "experience": _clean_str_value(other_justifications.get("experience"))
        or "Experience evidence is missing or weak.",
        "responsibilities": _clean_str_value(
            other_justifications.get("responsibilities")
        )
        or "Responsibility evidence is missing or weak.",
        "projects": _clean_str_value(other_justifications.get("projects"))
        or "Project evidence is missing or weak.",
        "location": _clean_str_value(other_justifications.get("location"))
        or "Location evidence is missing or not applicable.",
        "certification": _clean_str_value(
            other_justifications.get("certification")
        )
        or "Certification evidence is missing or weak.",
        "education": _clean_str_value(other_justifications.get("education"))
        or "Education evidence is missing or weak.",
    }

    raw_evals = llm_result.get("skill_evaluations")
    raw_evals = raw_evals if isinstance(raw_evals, list) else []

    eval_map = {}

    for item in raw_evals:
        if not isinstance(item, dict):
            continue

        jd_skill = str(item.get("jd_skill") or "").strip()

        if jd_skill not in jd_mandatory_skills:
            continue

        match_status = _normalize_match_status(item.get("match_status"))
        match_score = _safe_score_0_100(item.get("match_score", 0))

        # Guard: contradictory LLM output — "matched" with a very low
        # score is not trustworthy enough for full credit. Downgrade.
        if match_status == "matched" and match_score < 50.0:
            match_status = "partial"

        eval_map[jd_skill] = {
            "jd_skill": jd_skill,
            "skill_type": _clean_str_value(item.get("skill_type"))
            or "hard_technical",
            "match_status": match_status,
            "match_score": match_score,
            "evidence_confidence": _clean_str_value(
                item.get("evidence_confidence")
            )
            or "low",
            "matched_evidence": _safe_list_of_strings(
                item.get("matched_evidence")
            ),
            "missing_evidence": _safe_list_of_strings(
                item.get("missing_evidence")
            ),
        }

    skill_evaluations = []
    matched_skills = []
    partial_skills = []
    missing_skills = []
    total_skill_score = 0.0

    for jd_skill in jd_mandatory_skills:
        if jd_skill in eval_map:
            ev = eval_map[jd_skill]
        else:
            ev = {
                "jd_skill": jd_skill,
                "skill_type": "hard_technical",
                "match_status": "missing",
                "match_score": 0.0,
                "evidence_confidence": "low",
                "matched_evidence": [],
                "missing_evidence": [],
            }

        # Status-driven credit: matched=100, partial=clamped LLM score,
        # missing=0. Overwrite match_score so per-skill display stays
        # consistent with the overall skill_score.
        credit = _credit_for_evaluation(ev)
        ev["match_score"] = credit

        skill_evaluations.append(ev)
        total_skill_score += credit

        status = ev["match_status"]

        if status == "matched":
            matched_skills.append(jd_skill)
        elif status == "partial":
            partial_skills.append(jd_skill)
        else:
            missing_skills.append(jd_skill)

    llm_result["skill_evaluations"] = skill_evaluations
    llm_result["matched_skills"] = matched_skills
    llm_result["partial_skills"] = partial_skills
    llm_result["skills_partial"] = len(partial_skills)
    llm_result["missing_skills"] = missing_skills
    llm_result["skills_matched"] = len(matched_skills)
    llm_result["total_skills"] = len(jd_mandatory_skills)
    llm_result["skill_score"] = (
        round(total_skill_score / len(jd_mandatory_skills), 2)
        if jd_mandatory_skills
        else 0.0
    )

    return llm_result



# =============================================================================
# COMPETENCY GENERATION
# =============================================================================

GENERATE_COMPETENCIES_SYSTEM_PROMPT = """
You are an enterprise-grade interview competency generation engine.

Your task is to generate exactly 4 core interview competencies for a hiring assessment stage.

INPUT YOU WILL RECEIVE:
- stage_code
- stage_information
- mandatory_skills

You MUST use only provided stage_code, stage_information, and mandatory_skills.

RULES:
- Return ONLY valid JSON.
- Generate exactly 4 competencies.
- Each competency must be an umbrella capability.
- Across all 4 competencies, every mandatory skill should be covered at least once.
- Do NOT invent skills.
- Do NOT generate interview questions.
- Do NOT generate answers.
- covered_mandatory_skills must contain only exact values from mandatory_skills.
- Do NOT paraphrase skills inside covered_mandatory_skills.

OUTPUT JSON SCHEMA:
{
  "competencies": [
    {
      "competency_name": "string",
      "description": "string",
      "covered_mandatory_skills": ["string"],
      "evaluation_focus": "string"
    }
  ]
}

FINAL VALIDATION:
- JSON is valid.
- competencies count is exactly 4.
- all mandatory_skills are covered at least once.
- no interview questions are generated.
""".strip()


def _attach_missing_skills_to_competencies(
    *,
    competencies: list[dict],
    missing_skills: list[str],
) -> list[dict]:
    for skill in missing_skills:
        target = min(
            competencies,
            key=lambda item: len(item.get("covered_mandatory_skills") or []),
        )

        if skill not in target["covered_mandatory_skills"]:
            target["covered_mandatory_skills"].append(skill)

    return competencies


def _normalize_generated_competencies(
    *,
    parsed: dict,
    mandatory_skills: list[str],
) -> list[dict]:
    competencies = parsed.get("competencies")

    if not isinstance(competencies, list):
        raise HTTPException(
            status_code=500,
            detail="LLM response missing competencies list",
        )

    normalized = []
    allowed_skills = set(mandatory_skills)

    for item in competencies:
        if not isinstance(item, dict):
            continue

        competency_name = str(item.get("competency_name") or "").strip()
        description = str(item.get("description") or "").strip()
        evaluation_focus = str(item.get("evaluation_focus") or "").strip()

        raw_covered_skills = item.get("covered_mandatory_skills") or []

        if not isinstance(raw_covered_skills, list):
            raw_covered_skills = []

        covered_mandatory_skills = []

        for skill in raw_covered_skills:
            skill_text = str(skill).strip()

            if (
                skill_text in allowed_skills
                and skill_text not in covered_mandatory_skills
            ):
                covered_mandatory_skills.append(skill_text)

        if not competency_name:
            competency_name = "Core Competency"

        if not description:
            description = (
                "Evaluates the candidate's capability across the mapped mandatory skills."
            )

        if not evaluation_focus:
            evaluation_focus = (
                "Assess practical understanding, depth, and relevance to the interview stage."
            )

        normalized.append(
            {
                "competency_name": competency_name,
                "description": description,
                "covered_mandatory_skills": covered_mandatory_skills,
                "evaluation_focus": evaluation_focus,
            }
        )

    if not normalized:
        raise HTTPException(
            status_code=500,
            detail="LLM did not generate valid competencies",
        )

    covered_all = set()

    for item in normalized:
        covered_all.update(item["covered_mandatory_skills"])

    missing_skills = [
        skill
        for skill in mandatory_skills
        if skill not in covered_all
    ]

    if missing_skills:
        normalized = _attach_missing_skills_to_competencies(
            competencies=normalized,
            missing_skills=missing_skills,
        )

    return normalized


def _mock_generate_competencies(
    *,
    stage_code: str,
    stage_information: str,
    mandatory_skills: list[str],
) -> list[dict]:
    buckets = [[], [], [], []]

    for index, skill in enumerate(mandatory_skills):
        buckets[index % 4].append(skill)

    return [
        {
            "competency_name": "Core Technical and Domain Capability",
            "description": "Evaluates practical understanding and application of core mandatory skills.",
            "covered_mandatory_skills": buckets[0],
            "evaluation_focus": "Assess hands-on depth, correctness, and applied knowledge.",
        },
        {
            "competency_name": "Execution and Problem-Solving Approach",
            "description": "Evaluates structured thinking and execution effectiveness.",
            "covered_mandatory_skills": buckets[1],
            "evaluation_focus": "Assess problem-solving approach, ownership, and delivery clarity.",
        },
        {
            "competency_name": "Tools, Platforms, and Process Alignment",
            "description": "Evaluates proficiency with tools, systems, and process expectations.",
            "covered_mandatory_skills": buckets[2],
            "evaluation_focus": "Assess practical familiarity with relevant tools, systems, and workflows.",
        },
        {
            "competency_name": "Communication and Stakeholder Effectiveness",
            "description": "Evaluates communication, collaboration, and stakeholder management capabilities.",
            "covered_mandatory_skills": buckets[3],
            "evaluation_focus": "Assess clarity, influence, collaboration, and stakeholder handling.",
        },
    ]


def _llm_generate_competencies(
    *,
    stage_code: str,
    stage_information: str,
    mandatory_skills: list[str],
) -> list[dict]:
    settings = Settings()

    cleaned_mandatory_skills = [
        str(skill).strip()
        for skill in mandatory_skills
        if str(skill).strip()
    ]

    if not cleaned_mandatory_skills:
        raise HTTPException(
            status_code=400,
            detail="mandatory_skills must contain at least one valid skill",
        )

    if settings.llm_provider == "mock":
        return _mock_generate_competencies(
            stage_code=stage_code,
            stage_information=stage_information,
            mandatory_skills=cleaned_mandatory_skills,
        )

    if settings.llm_provider != "azure":
        raise HTTPException(
            status_code=500,
            detail="Unsupported LLM provider",
        )

    prompt = json.dumps(
        {
            "stage_code": stage_code,
            "stage_information": stage_information,
            "mandatory_skills": cleaned_mandatory_skills,
        },
        ensure_ascii=False,
    )

    client = _azure_client(
        settings.azure_openai_api_key,
        settings.azure_openai_api_version,
        settings.azure_openai_endpoint,
    )

    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": GENERATE_COMPETENCIES_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(_strip_json_fence(content))

    return _normalize_generated_competencies(
        parsed=parsed,
        mandatory_skills=cleaned_mandatory_skills,
    )