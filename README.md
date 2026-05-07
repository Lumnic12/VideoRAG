# 🎬 Semantic Video Synthesizer

> **AI-powered video analysis platform** — Upload videos, extract keyframes, transcribe audio, and chat with your video content using a conversational AI. 100% local processing.

![License](https://img.shields.io/badge/license-MIT-purple)
![Python](https://img.shields.io/badge/python-3.12+-blue)
![React](https://img.shields.io/badge/react-19-61dafb)
![Docker](https://img.shields.io/badge/docker-ready-2496ED)

---

## ✨ Features

| Feature | Technology | Description |
|---------|-----------|-------------|
| 🎥 **Video Upload** | FastAPI + Celery | Async upload with real-time progress via WebSocket |
| 🖼️ **Keyframe Extraction** | OpenCV + SSIM | Intelligent frame selection based on structural similarity |
| 📝 **OCR Text Extraction** | Windows OCR (WinRT) | Reads all on-screen text from slides, MCQs, diagrams |
| 🎙️ **Audio Transcription** | faster-whisper | Local Whisper model — no cloud APIs needed |
| 🧠 **Conversational Chat** | Ollama (gemma3:1b) | Multi-turn chat with full video context |
| 🔍 **Vector Search** | FAISS + nomic-embed | Fast semantic retrieval across indexed content |
| 🎨 **Modern UI** | React + Vite | Dark-mode glassmorphism design with markdown rendering |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Frontend (React + Vite → Nginx)         :3000           │
├─────────────────────────────────────────────────────────┤
│ Backend API (FastAPI + Uvicorn)          :8000           │
│   ├── /api/v1/video    → Upload + Process               │
│   ├── /api/v1/query    → RAG Chat                       │
│   ├── /api/v1/videos   → Video Library                  │
│   └── /ws/progress     → Real-time Updates              │
├─────────────────────────────────────────────────────────┤
│ Celery Worker                                           │
│   ├── SSIM Keyframe Extraction                          │
│   ├── Windows OCR / Tesseract                           │
│   ├── Whisper Audio Transcription                       │
│   ├── Ollama Enrichment (gemma3:1b)                     │
│   └── FAISS Vector Indexing                             │
├─────────────────────────────────────────────────────────┤
│ Redis             │ Ollama            │ FAISS           │
│ (broker/cache)    │ (LLM + embeddings)│ (vector store)  │
└───────────────────┴───────────────────┴─────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+**
- **Node.js 20+**
- **Redis** — `redis-server` or Docker
- **Ollama** — [ollama.ai](https://ollama.ai)
- **FFmpeg** — for audio extraction

### 1. Install Ollama Models

```bash
ollama pull gemma3:1b
ollama pull nomic-embed-text
ollama serve  # keep running
```

### 2. Clone & Configure

```bash
git clone <repo-url>
cd main_cap
cp .env.example .env
# Edit .env if needed (defaults work for local dev)
```

### 3. Backend Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac

pip install -r requirements.txt
```

### 4. Frontend Setup

```bash
cd frontend
npm install
```

### 5. Start Everything

Open **3 terminals**:

```powershell
# Terminal 1: Backend API
cd backend && .venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000

# Terminal 2: Celery Worker
cd backend && .venv\Scripts\python.exe -m celery -A services.task_orchestrator:celery_app worker --pool=solo --loglevel=info

# Terminal 3: Frontend
cd frontend && npm run dev
```

Open **http://localhost:3000** 🎉

---

## 🐳 Docker Deployment

### Production

```bash
# Make sure Ollama is running on the host
ollama serve

# Build and start all services
docker compose up --build -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

### With Monitoring (Flower UI)

```bash
docker compose --profile monitoring up --build -d
# Flower UI at http://localhost:5555
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| Frontend | 3000 | React app (nginx) |
| Backend | 8000 | FastAPI REST API |
| Redis | 6379 | Message broker |
| Flower | 5555 | Celery monitoring (optional) |

---

## 📁 Project Structure

```
main_cap/
├── backend/
│   ├── api/routes/        # REST endpoints
│   │   ├── video.py       # Upload, list, delete videos
│   │   └── query.py       # RAG chat endpoint
│   ├── core/config.py     # Pydantic settings
│   ├── models/schemas.py  # Request/response models
│   ├── services/
│   │   ├── rag_service.py       # FAISS indexing + LLM chat
│   │   ├── vlm_service.py       # OCR + keyframe analysis
│   │   ├── audio_service.py     # Whisper transcription
│   │   ├── frame_extractor.py   # SSIM keyframe extraction
│   │   └── task_orchestrator.py # Celery pipeline
│   └── main.py            # FastAPI app entry
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Chat.tsx   # Conversational chat interface
│   │   │   ├── Upload.tsx # Video upload page
│   │   │   ├── Home.tsx   # Dashboard
│   │   │   └── ...
│   │   ├── components/    # Sidebar, Layout
│   │   └── lib/api.ts     # API client
│   └── Dockerfile         # nginx production build
├── docker-compose.yml     # Production deployment
├── Dockerfile.backend     # Multi-stage backend image
└── .env.example           # Configuration template
```

---

## 🔧 Configuration

All config is via environment variables (`.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434/v1` | Ollama API endpoint |
| `OLLAMA_MODEL` | `gemma3:1b` | Chat LLM model |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `MAX_UPLOAD_SIZE_MB` | `500` | Max video upload size |
| `SSIM_THRESHOLD` | `0.95` | Frame similarity threshold |

---

## 📋 API Endpoints

### Video Management
- `POST /api/v1/video/upload` — Upload video for processing
- `GET /api/v1/videos` — List all processed videos
- `DELETE /api/v1/videos/{id}` — Delete video and all data
- `GET /api/v1/videos/{id}/status` — Get processing status

### Chat / Query
- `POST /api/v1/query` — Send question with conversation history
- `GET /api/v1/keyframes/{video_id}` — Get keyframe metadata

### System
- `GET /health` — Health check (Redis, Celery status)
- `WS /ws/progress/{job_id}` — Real-time processing progress

---

## 🛠️ Tech Stack

**Backend:** Python 3.12 · FastAPI · Celery · Redis · FAISS · Ollama · Whisper  
**Frontend:** React 19 · TypeScript · Vite · CSS (custom design system)  
**Deployment:** Docker · nginx · docker-compose  
**AI:** gemma3:1b (chat) · nomic-embed-text (embeddings) · faster-whisper (STT) · Windows OCR (vision)

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
