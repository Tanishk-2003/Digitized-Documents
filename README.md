# 💊 Pharma Stock & Sale Statement Intelligence (Pharma DI)

> **A local-only, privacy-first Document Intelligence pipeline that transforms heterogeneous, photographed pharmaceutical distributor statements into standardized, validated canonical datasets — without sending data to external APIs.**

---

## 📌 Overview

Pharmaceutical distributors across India and worldwide use diverse ERP software (Marg, Tally, Busy, AlignBooks, PharmaSoft, custom legacy systems) to generate monthly **Stock & Sale statements**. These statements arrive as camera photographs of folded, skewed, dot-matrix printed paper documents with vastly different layouts, hierarchical headers, and naming conventions.

**Pharma DI** solves this document understanding challenge on-premise without relying on hosted AI/OCR APIs (no OpenAI, no Google Document AI, no AWS Textract). It automatically:
1. **Preprocesses noisy camera photographs** (boundary detection, perspective rectification, deskewing, dewarping, shadow removal).
2. **Extracts text & bounding boxes on-box** via PaddleOCR.
3. **Reconstructs complex table structures & hierarchical headers** (`OPENING` → `QTY`/`VALUE`, `RECEIPT` → `QTY`/`VALUE`, etc.).
4. **Tracks sloped/curved row baselines** to accurately assign numbers to their corresponding product items.
5. **Maps arbitrary distributor column names into a single Uniform Canonical Schema** using a deterministic 5-tier resolution hierarchy.
6. **Validates accounting & arithmetic integrity** (Reconciliation formulas, rate coherence, totals cross-footing).
7. **Provides a React Review UI** with side-by-side original image inspection, per-field confidence visualizers, and a continuous feedback loop that promotes human corrections into future automatic mapping rules.

---

## 🏗️ Architecture & Pipeline Flow

```mermaid
flowchart TD
    A[Photographed Statement / Image / PDF] --> B[1. Preprocess: Boundary, Deskew, Dewarp, Shadow Removal]
    B --> C[2. Quality Gate: Blur, Resolution, Framing Checks]
    C --> D[3. On-Box OCR & Token Geometry Engine]
    D --> E[4. Region Segmentation: Header, Meta, Table, Totals, Footer]
    E --> F[5. Hierarchical Header Reconstruction & Column Banding]
    F --> G[6. Sloped Row Baseline & Cell Value Assembly]
    G --> H[7. Document & Distributor Detection]
    H --> I[8. Semantic Column Mapping to Canonical Schema]
    I --> J[9. Product Master Resolution]
    J --> K[10. Validation Engine: R1-R7 Rules & Arithmetic Reconcile]
    K -->|High Confidence & Valid Math| L[(System of Record: MySQL / SQLite)]
    K -->|Discrepancy / Unresolved Column| M[React Review UI: Side-by-Side Crop & 1-Click Map]
    M -->|Approve / Correct| L
    M -.->|Feedback Loop: Promote Aliases| I
    L --> N[Excel Export / REST API]
```

---

## 📊 The 3-Level Data Model & Canonical Schema

The system organizes extracted statement data into a 3-level relational hierarchy:

1. **Level 1 — Document:** Metadata identifying the distributor, covered pharma company, statement period, and document classification (`summary` vs `product_level`).
2. **Level 2 — Product:** Item description, resolved master catalogue ID, HSN code, pack size, and unit price/rate (PTR/PTS).
3. **Level 3 — Transaction & Inventory Movements:** Quantities and valuations for opening stock, purchases/receipts, free goods, sales/issues, market returns, supplier returns, expiry/damage dumps, and closing balances.

### Standardized Canonical Output Schema

| Field Category | Canonical Field Names | Description |
|---|---|---|
| **Provenance** | `distributor_id`, `distributor_name`, `company_name`, `statement_from`, `statement_to`, `document_type`, `source_document`, `page_number` | Full audit trail and distributor identity |
| **Product** | `product_id`, `product_name_raw`, `hsn_code`, `pack`, `rate` | Master-resolved product dimensions |
| **Quantities** | `opening_quantity`, `received_quantity`, `free_received_quantity`, `sales_quantity`, `free_sales_quantity`, `sales_return_quantity`, `purchase_return_quantity`, `expired_quantity`, `closing_quantity` | Complete stock movement balances |
| **Valuations** | `opening_value`, `received_value`, `sales_value`, `closing_value` | Monetary stock balances |
| **Status & Meta** | `months_to_expiry`, `stock_status`, `source_field_breakdown`, `unmapped_columns`, `extraction_confidence`, `review_status`, `review_reasons` | Quality scores and unmapped column preservation |

---

## 🗂️ Project Repository Structure

```
Digitize_doc/
├── alembic/                 # Database migrations (Alembic)
├── config/                  # Configuration & YAML dictionaries
│   ├── column_mappings.yaml # Semantic column aliases & hierarchical paths
│   ├── distributors.yaml    # Distributor master & GSTIN patterns
│   └── validation_rules.yaml# Arithmetic reconciliation formulas per family
├── data/
│   ├── input/               # Sample document images (e.g. doc1.jpg - doc6.jpg)
│   ├── masters/             # Reference product master catalogue (products.csv)
│   ├── interim/             # Pipeline step outputs & local SQLite DB (ignored in git)
│   ├── uploads/             # API runtime uploaded documents (ignored in git)
│   └── output/              # Exported canonical Excel spreadsheets (ignored in git)
├── src/pharma_di/           # Core Python Package
│   ├── api/                 # FastAPI routes (documents, review queue, static images)
│   ├── assemble/            # Canonical schema assembly logic
│   ├── detect/              # Distributor, company, period & fingerprint detection
│   ├── export/              # Excel (.xlsx) flat schema generator
│   ├── graph/               # LangGraph state graph & node orchestration
│   ├── layout/              # Region segmentation, hierarchical headers, sloped rows
│   ├── mapping/             # 5-tier column resolver & feedback alias updater
│   ├── ocr/                 # PaddleOCR engine wrapper & content-addressed cache
│   ├── persist/             # SQLAlchemy ORM models & repository layer
│   ├── preprocess/          # OpenCV boundary crop, deskew, dewarp, illumination
│   ├── resolve/             # Product master matching (HSN & fuzzy name)
│   ├── schemas/             # Pydantic v2 domain & API schemas
│   ├── validate/            # Validation engine (R1-R7 rules, reconciliation math)
│   └── workers/             # Async ThreadPoolExecutor background JobManager
├── tests/
│   ├── unit/                # 265+ fast, isolated unit tests (all modules & API)
│   └── integration/         # Real OCR integration tests
├── ui/                      # React Review Single-Page Application (Vite + React 19)
│   ├── src/                 # Pages (Upload, Jobs, Documents, Review Queue, Detail)
│   └── vite.config.js       # Vite proxy to FastAPI backend (port 8000)
├── scripts/                 # CLI tools (run_pipeline.py, bootstrap_products.py)
├── pyproject.toml           # Python package metadata & dependencies
└── README.md                # Project documentation
```

---

## ⚡ Quick Start & Installation

### 1. Prerequisites
- **Python 3.10+** (Tested on Python 3.12)
- **Node.js 18+** & **npm** (for the Review UI)
- **uv** (recommended for fast virtualenv setup) or standard `venv`

### 2. Python Environment Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd Digitize_doc

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install dependencies in editable mode
pip install -e .
```

### 3. Database Initialization

By default, the pipeline uses SQLite (`data/interim/pharma_di.db`). To connect to MySQL instead, simply export the `DATABASE_URL` environment variable:

```bash
# Optional: Point to MySQL (defaults to local SQLite if unset)
# export DATABASE_URL="mysql+pymysql://user:password@localhost:3306/pharma_di"

# Run database migrations
alembic upgrade head
```

### 4. React UI Setup

```bash
cd ui
npm install
cd ..
```

---

## 🚀 Running the System

### Option A: Web API & Interactive Review UI (Recommended)

1. **Start the FastAPI Backend Server** (runs on `http://localhost:8000`):
   ```bash
   python -m uvicorn pharma_di.api.app:app --host 127.0.0.1 --port 8000 --reload
   ```

2. **Start the React Review UI** (runs on `http://localhost:5173`):
   ```bash
   cd ui
   npm run dev
   ```

3. Open `http://localhost:5173` in your browser to:
   - **Upload:** Drag-and-drop photographed statements.
   - **Jobs:** Monitor live background OCR and pipeline execution stages.
   - **Review Queue:** Review flagged documents side-by-side with the source image crop.
   - **Promote Columns:** Map unmapped headers with 1 click to update `column_mappings.yaml` permanently.
   - **Export:** Download validated statements as Excel spreadsheets.

---

### Option B: CLI Pipeline Execution

Run the pipeline directly from the command line on any input photograph:

```bash
# Process a single document
python scripts/run_pipeline.py --input data/input/doc6.jpg --output-excel data/output/doc6_result.xlsx

# Process with verbose debug tracing (saves step crops in data/interim/)
python scripts/run_pipeline.py --input data/input/doc1.jpg --debug
```

---

## 🧪 Running the Test Suite

The project features a comprehensive test suite (265+ unit tests) verifying state transitions, preprocessing algorithms, header grouping, sloped row matching, database persistence, and API contracts:

```bash
# Run all unit tests (fast, runs in ~15s without waiting for PaddleOCR)
pytest tests/unit/ -v

# Run API contract & UI integration tests
pytest tests/unit/test_api.py tests/unit/test_p10_review_ui.py -v
```

---

## 🌐 REST API Endpoints

Interactive Swagger documentation is available at `http://localhost:8000/docs`.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/documents/upload` | Upload document image (multipart/form-data); returns HTTP 202 with `job_id` |
| `GET` | `/api/jobs/{job_id}` | Get real-time status and execution stage of a processing job |
| `GET` | `/api/jobs` | List all historical and active background jobs |
| `GET` | `/api/documents` | List all processed documents with row and review counts |
| `GET` | `/api/documents/{document_id}` | Get full document details, metadata, and canonical rows |
| `GET` | `/api/documents/{document_id}/export/excel` | Stream canonical Stock & Sale statement as an `.xlsx` file |
| `GET` | `/api/review-queue` | List all documents requiring human review with specific failure reasons |
| `POST` | `/api/review/{document_id}/approve` | Mark all flagged rows for a document as approved |
| `POST` | `/api/review/{document_id}/correct` | Submit row corrections & promote confirmed column aliases to config |
| `GET` | `/api/static/{file_path}` | Serve source document images for side-by-side UI inspection |
| `GET` | `/health` | Service health status check |

---

## 🔒 Privacy & Operational Principles

1. **Strict Privacy:** Zero document images, extracted text, or derived business intelligence ever leave your local machine or VPC.
2. **Deterministic-First Extraction:** Over 95% of column headers and row alignments are resolved through geometry and dictionary rules rather than nondeterministic LLM calls.
3. **Zero Guesswork:** Ambiguous or unmapped columns are never hallucinated; their raw cells survive in `unmapped_columns` and route safely to the human review queue.
4. **Active Learning Loop:** Every human correction in the UI promotes new aliases to `config/column_mappings.yaml` so the same format resolves deterministically on subsequent runs.

---

## 📄 License

This project is proprietary and intended for private pharmaceutical supply-chain document intelligence.
