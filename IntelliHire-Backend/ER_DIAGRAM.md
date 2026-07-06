# ER Diagram

```mermaid
erDiagram
    JOB_DESCRIPTIONS ||--o{ SCREENING_RESULTS : "is_scored_against"
    CANDIDATES ||--o{ RESUMES : "owns"
    CANDIDATES ||--o{ SCREENING_RESULTS : "gets_scored"
    RESUMES ||--o{ SCREENING_RESULTS : "used_for"

    JOB_DESCRIPTIONS ||--o{ APPLICATIONS : "receives_applications"
    CANDIDATES ||--o{ APPLICATIONS : "applies_to"
    RESUMES ||--o{ APPLICATIONS : "current_resume"
    SCREENING_RESULTS ||--o{ APPLICATIONS : "latest_screening"

    APPLICATIONS ||--o{ APPLICATION_STAGE_HISTORY : "tracks_stage_changes"
    APPLICATIONS ||--o{ RECRUITER_ASSESSMENTS : "has"

    JOB_DESCRIPTIONS {
        bigint jd_id PK
        varchar req_id UK
        varchar grade
        text title
        text department
        text location
        text experience
        text role_summary
        jsonb responsibilities
        jsonb mandatory_skills
        jsonb good_to_have_skills
        jsonb problem_statements
        text jd_s3_key
        uuid jd_file_uuid
        boolean jd_uploaded
        boolean jd_parsed
        varchar jd_source_type
        text jd_raw_text
        varchar jd_parse_status
        varchar status
        timestamp created_at
        timestamp updated_at
    }

    CANDIDATES {
        bigint candidate_id PK
        varchar full_name
        varchar email
        varchar phone
        boolean duplicate_flag
        timestamp created_at
    }

    RESUMES {
        bigint resume_id PK
        bigint candidate_id FK
        uuid file_uuid UK
        varchar file_name
        text s3_key
        text extracted_text
        jsonb parsed_resume_json
        boolean is_latest
        timestamp uploaded_at
    }

    SCREENING_RESULTS {
        bigint screening_result_id PK
        bigint jd_id FK
        bigint candidate_id FK
        bigint resume_id FK
        numeric skill_score
        numeric other_score
        numeric overall_score
        int skills_matched
        int total_skills
        jsonb matched_skills
        jsonb missing_skills
        jsonb other_score_breakdown
        varchar match_status
        timestamp screened_at
    }

    APPLICATIONS {
        bigint application_id PK
        bigint jd_id FK
        bigint candidate_id FK
        bigint current_resume_id FK
        bigint latest_screening_result_id FK
        varchar current_stage
        varchar status
        timestamp created_at
        timestamp updated_at
    }

    APPLICATION_STAGE_HISTORY {
        bigint history_id PK
        bigint application_id FK
        varchar from_stage
        varchar to_stage
        varchar changed_by
        text remarks
        timestamp changed_at
    }

    RECRUITER_ASSESSMENTS {
        bigint assessment_id PK
        bigint application_id FK
        jsonb answers
        text summary_feedback
        varchar status
        timestamp created_at
        timestamp updated_at
    }
}
```

## Relationship summary
- one **job description** can have many screening results
- one **candidate** can have many resumes
- one **candidate** can have many screening results
- one **resume** belongs to one candidate and can produce one or more screening results
- one **job description** can have many applications
- one **candidate** can have many applications, but only one per JD
- one **application** is the pipeline backbone for later stages
