# 🚀 rt Report Automation

A microservice to automate the generation and distribution of rt reports.

---

## 🧑‍💻 Getting Started

1. **Clone the repo**:

   ```bash
   git clone https://github.com/rtCamp/rt-report-automation.git
   cd rt-report-automation
   ```

2. **Set up environment variables**:

   Create a `.env` file in the root directory based on the provided `.env.example`.

3. **Build and start the application**:

   Using Docker Compose:

   ```bash
   make build
   make start
   ```

   To stop the application:

   ```bash
   make down
   ```

   This will start the FastAPI server on `http://localhost:8000`.
   The automatic API docs will be available at `http://localhost:8000/docs`.
