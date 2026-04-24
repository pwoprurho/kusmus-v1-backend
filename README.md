# Kusmus AI — Sovereign Intelligence Infrastructure

The Kusmus AI platform is a high-density, sovereign intelligence ecosystem designed for enterprise-grade AI orchestration. It features a hybrid-agent architecture, secure telemetry, and managed LLM nodes, allowing clients to maintain full data sovereignty while leveraging cutting-edge frontier models.

## 🚀 Key Features

*   **Sovereign Node Orchestration**: Provision and manage dedicated LLM instances (vLLM/Ollama) on private GPU infrastructure (RunPod/On-Prem).
*   **Neutral Sandbox**: A secure testing environment for AI agents with real-time telemetry and threat-aware monitoring.
*   **Multi-Agent Intelligence**: Specialized personas (Tax Agent, Market Sentinel, STEM Physics) collaborating via a unified WebSocket-driven terminal.
*   **Hybrid RAG/Analysis**: High-fidelity retrieval and analysis pipelines for complex document structures and live market data.
*   **Security-First Foundation**: Hardened with Flask-Talisman (CSP/HSTS), CSRF protection, and cryptographically signed audit trails.

---

## 🛠 Tech Stack

*   **Backend**: Flask (Python 3.12+)
*   **Real-time**: Flask-SocketIO (Eventlet)
*   **Database**: Supabase (PostgreSQL) + Psycopg3 for migrations
*   **AI Engine**: Google Gemini (Flash v2.5) + Sovereign vLLM/Ollama Nodes
*   **Orchestration**: Managed RunPod GPU Pods
*   **Security**: Flask-Talisman, Flask-WTF, Flask-Limiter

---

## 🚦 Getting Started

### 1. Prerequisites
*   Python 3.10+
*   Supabase Project (URL + Service Role Key)
*   Google Gemini API Key(s)

### 2. Environment Setup
Clone the repository and initialize the environment:
```bash
python -m venv venv
source venv/bin/activate  # venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
```
Edit `.env` and provide your API keys and database credentials.

### 3. Database Migrations
Kusmus uses a custom migration runner to ensure schema parity across environments.
```bash
python scripts/migrate.py
```

### 4. Running the Application
```bash
python app.py
```
The application will be available at `http://localhost:8000`.

---

## 🏗 Operations & Scaling

### Database Migrations
New schema changes should be added as `.sql` files in the `database/` directory. The migration runner will execute them in alphabetical order.

### Adding AI Personas
New sandbox personas can be registered in `services/demo_registry.py`. Each persona requires a system instruction and a unique identifier.

---

## 🔒 Security Audit
The platform undergoes regular automated hardening. Current security features include:
*   **SRRF Protection**: Validated outbound requests for Sovereign Nodes.
*   **CSRF Enforcement**: All state-changing actions are tokenized.
*   **Information Sanitization**: Production error handlers strip tracebacks to prevent reconnaissance.
*   **Secure Headers**: Strict CSP policy enforced via Talisman.

---

## 📜 License
Internal Enterprise Use Only. (C) 2026 Kusmus AI Systems.
