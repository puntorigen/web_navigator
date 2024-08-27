# Web Navigator 🚀

Welcome to **Web Navigator**, your autonomous web automation tool powered by FastAPI and Playwright. This project is designed to automate complex browser tasks with ease, leveraging advanced AI capabilities for error correction and dynamic task execution.

## 🌟 Features

- **FastAPI Backend**: High-performance backend powered by FastAPI.
- **Playwright Integration**: Robust support for web automation with Playwright and stealth browsing.
- **AI-Powered Command Healing**: Automatically corrects and retries failed commands using GPT models.
- **Docker Support**: Easily deployable via Docker.

## 🛠️ Installation

To get started with Web Navigator, follow these steps:

### Prerequisites
- Docker
- Docker Compose

### Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/web_navigator.git
   cd web_navigator
   ```

2. Create a `.env` file in the project root and add your OpenAI API key:
   ```env
   OPENAI_API_KEY=your_openai_api_key
   ```

3. Build and run the Docker container:
   ```bash
   docker-compose up --build
   ```

The app will be available at `http://localhost:80`.

## 📄 Usage

Web Navigator accepts user prompts to navigate and interact with web pages autonomously. Here's an example of how you can use the `/navigate` endpoint.

### Example Request
```json
POST /navigate HTTP/1.1
Host: localhost
Content-Type: application/json
{
  "prompt": "Go to https://example.com and take a screenshot."
}
```

### Example Response
```json
{
  "message": "Task completed successfully",
  "state": {
    "steps": [
      {
        "command": "await page.goto('https://example.com', timeout=30000, wait_until='networkidle')",
        "status": "success",
        "reason": "Initial navigation to the extracted URL"
      }
    ]
  }
}
```

## 📚 License

This project is licensed under the MIT License. See the [LICENSE](./LICENSE) file for details.

Enjoy automating your web tasks with Web Navigator! ✨
