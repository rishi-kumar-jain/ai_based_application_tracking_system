# ai_based_application_tracking_system
# IntelliHire Backend

This package is the final backend scaffold aligned to the latest agreed flow.
 
## Core principles
- table name is `job_descriptions`
- primary key is `jd_id`
- no separate file asset table
- uploaded JD is stored first, parsed later
- `problem_statements` are stored on the JD row itself
- screening data is saved for every processed resume
- pipeline uses `applications`
- duplicate candidate handling:
  - email first
  - then phone
  - same candidate + same JD updates application, no duplicate application row
  - same candidate + different JD creates a separate application

## End-to-end flow

### 1. Upload JD
`POST /job-descriptions/upload-jd`
- recruiter sends `req_id`, `grade`, and JD file
- backend uploads file to storage
- backend creates a new draft row in `job_descriptions`
- backend returns `jd_id`

### 2. Validate JD
`GET /job-descriptions/id={jd_id}`
- frontend loads the draft row
- shows download link if uploaded

`POST /job-descriptions/parse-uploaded-jd`
- frontend calls this when user clicks parse/generate on Validate JD page
- backend downloads the JD file
- backend extracts text
- backend sends text to LLM
- backend updates parsed fields in the same row

`POST /job-descriptions/save`
- used for:
  - create from scratch
  - validate page save draft
  - validate page next

### 3. Problem Statements
`POST /job-descriptions/problem-statements/save`
- updates `problem_statements` on the existing JD row by `jd_id`
- each item contains:
  - question
  - key_kpis
  - is_mandatory
- minimum 3 mandatory items required

### 4. Screening
`POST /screening/upload-resumes`
- accepts `jd_id` and multiple resumes
- each resume is stored
- candidate is found or created
- screening result is stored for every resume

`GET /screening-results/jd_id={jd_id}`
- returns all screening results for the JD

### 5. Pipeline
`POST /pipeline/add`
- creates or updates one application row per candidate + JD

`POST /pipeline/move`
- updates application stage and writes stage history

`GET /pipeline/jd_id={jd_id}`
- returns pipeline items for the JD

### 6. Recruiter Assessment
`GET /assessments/form/application_id={application_id}`
- returns problem statements for scoring

`POST /assessments/save`
- saves draft or submitted recruiter assessment

`GET /assessments/application_id={application_id}`
- fetches saved assessment

## API list

### Health
- `GET /`
- `GET /health`

### Job Descriptions
- `POST /job-descriptions/upload-jd`
- `POST /job-descriptions/parse-uploaded-jd`
- `POST /job-descriptions/save`
- `POST /job-descriptions/problem-statements/save`
- `GET /job-descriptions/id={jd_id}`

### Screening
- `POST /screening/upload-resumes`
- `GET /screening-results/jd_id={jd_id}`

### Pipeline
- `POST /pipeline/add`
- `POST /pipeline/move`
- `GET /pipeline/jd_id={jd_id}`

### Assessments
- `GET /assessments/form/application_id={application_id}`
- `POST /assessments/save`
- `GET /assessments/application_id={application_id}`

## Local run
1. copy `.env.example` to `.env`
2. fill `DATABASE_URL`
3. for first run on empty schema, keep `INIT_DB_ON_STARTUP=true`
4. run:
   ```bash
   uvicorn app.main:app --reload
   ```
5. open `/docs`

## Docker local run
```bash
docker build -t intellihire-backend .
docker run --env-file .env -p 8000:8000 intellihire-backend
```

## Lambda note
For Lambda:
- set `INIT_DB_ON_STARTUP=false` after initial schema/table creation
- switch Dockerfile entrypoint to `awslambdaric`

## ER Diagram
See `ER_DIAGRAM.md`
# ai_based_application_tracking_system

