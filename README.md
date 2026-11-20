# A.S.P.I.D.A.

**AI Security Proxy for Injection Defense & Anonymization.**

Our submission for Netcompany's Hackathon 2026, Challenge 3: Shadow AI protection and
data protection. A demo of the project can be found in the following link: https://youtu.be/B4N4U1_vQvQ

## The problem

Many people chat with AI tools every day and share personal data without noticing:
names, tax numbers, bank accounts, passwords. Inside a company, AI agents that can read
client records can also be tricked into leaking them.

## Our answer

A.S.P.I.D.A. sits between the user and the AI tool. It finds the personal data in a
message, **replaces it with placeholders**, sends the masked message to the AI, and
**puts the real values back** in the answer. The user notices nothing; the AI never sees
the data.

```
You typed:        Reply to Maria Papadopoulou, AFM 669293096 ...
The AI saw:       Reply to <CLIENT_1>, AFM <AFM_1> ...
You received:     Dear Maria Papadopoulou, thank you for ...
```

The same idea protects a company's AI agents: the agent only ever holds placeholders, so
even if it is tricked, it can only leak placeholders.

## Start it

**Requirements (MANDATORY):** Docker and an OpenAI API key.

**Set Up:**

1. ```bash
   git clone https://github.com/Zed765/Chat-GTP.git
   ```

2. ```bash
   cd Chat-GTP
   ```

3. ```bash
   cp .env.example .env
   ```

4. Open `.env` and you **MUST** fill in `OPENAI_API_KEY` with your API key.

5. ```bash
   docker compose up --build
   ```

To see the project, open in your browser the address: **http://localhost:8080**.
