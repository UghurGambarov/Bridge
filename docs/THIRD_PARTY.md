# Third-party dependencies

All dependencies are permissively licensed. No agent frameworks (LangChain, LangGraph, CrewAI, AutoGen, ...) are used.

## Backend runtime (`backend/requirements.txt`)

| Package | Purpose | License |
|---|---|---|
| FastAPI | HTTP API | MIT |
| Uvicorn | ASGI server | BSD-3-Clause |
| Pydantic v2 | Schemas, strict validation | MIT |
| SQLModel | ORM models | MIT |
| SQLAlchemy | Database toolkit | MIT |
| pdfplumber (+ pdfminer.six, pypdfium2, Pillow) | PDF text and character forensics | MIT (pdfminer.six MIT; pypdfium2 Apache-2.0 / BSD-3-Clause; Pillow MIT-CMU) |
| reportlab | Sample documents and receipt PDFs | BSD-3-Clause |
| Jinja2 | HTML reports | BSD-3-Clause |
| httpx | HTTP client for LLM providers | BSD-3-Clause |
| PyYAML | Config files | MIT |
| python-multipart | File uploads | Apache-2.0 |
| python-dotenv | `.env` loading | BSD-3-Clause |

## Optional

| Package | Purpose | License |
|---|---|---|
| anthropic | Anthropic provider (`LLM_PROVIDER=anthropic`); imported only when selected | MIT |

## Development only (`backend/requirements-dev.txt`)

| Package | Purpose | License |
|---|---|---|
| pytest | Tests | MIT |
