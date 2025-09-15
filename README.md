# 🤖 rt Report Automation

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
   The API docs will be available at `http://localhost:8000/docs`.

---

## 📦 Development Workflow

### 🔍 Setting up pre-commit hooks

To ensure code quality and consistency, pre-commit hooks are set up using the `pre-commit` tool. Follow these steps to set it up:

1. **Install pre-commit**:

   If you haven't installed `pre-commit` yet, you can do so using pip:

   ```bash
   pip install pre-commit
   ```

2. **Install the pre-commit hooks**:
   Run the following command in the root directory of the project:

   ```bash
   pre-commit install
   ```

### 🛠️ Local Setup for Inngest

Inngest is used for orchestrating workflows. To learn in detail about its dev server, visit [Inngest Dev Server](https://www.inngest.com/docs/dev-server).

Run the following command to start the Inngest dev server:

```bash
npx inngest-cli@latest dev

# You can specify the URL of your development `serve` API endpoint
npx inngest-cli@latest dev -u http://localhost:8000/api/inngest --no-discovery
```
