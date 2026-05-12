# Deploying to Streamlit Cloud

End state: a public URL where you can open the app on any device. Free tier is plenty.

**Hard rule before you start:** this app sends transcript text to Anthropic. Synthetic / training data only — no real patient identifiers, ever. Do not record or paste real handoffs into the deployed app.

---

## One-time setup

### 1. Install git (if you don't have it)

In PowerShell:

```powershell
git --version
```

If you see a version number, skip ahead. If not, download from <https://git-scm.com/download/win> and run the installer — defaults are fine.

### 2. Initialize git in the project

```powershell
cd "C:\Users\vince\Documents\MBA\SubI Handoff Copilot"
git init
git add .gitignore
git commit -m "Add gitignore"
```

The `.gitignore` is committed *first and alone* so the next `git add` doesn't pull in your `.env` or cache before git is told to ignore them.

### 3. Verify nothing sensitive is staged

```powershell
git status
git add .
git status
```

The second `git status` should show your code files but **NOT** `.env`, `.cache/`, `outputs/`, or `.venv/`. If any of those appear, stop and check `.gitignore` is in the project root.

### 4. First real commit

```powershell
git commit -m "Initial commit of sub-i copilot"
```

### 5. Create a GitHub repo

In a browser:

1. Go to <https://github.com/new>
2. Repository name: `sub-i-copilot` (or whatever you like)
3. **Public** (Streamlit Cloud free tier requires public). The repo will contain no secrets thanks to `.gitignore`.
4. Do NOT initialize with README / .gitignore / license (you already have them locally).
5. Create.

GitHub will show you a "push existing repository" snippet. It looks like:

```powershell
git remote add origin https://github.com/<your-username>/sub-i-copilot.git
git branch -M main
git push -u origin main
```

Run those three lines in PowerShell. On the `git push`, you'll be prompted to authenticate — typically a browser pop-up to GitHub. Confirm.

### 6. Deploy on Streamlit Cloud

1. Go to <https://share.streamlit.io> and sign in with GitHub.
2. Click "New app".
3. Select your `sub-i-copilot` repo, `main` branch, `app.py` as the main file.
4. Click "Advanced settings" → "Secrets". Paste:

   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```

   Use your real key. Streamlit Cloud encrypts these and exposes them as `st.secrets`. `app.py` already bridges them into `os.environ` so the Anthropic SDK finds them.

5. Deploy. First build takes 3–5 minutes (installs your dependencies including `faster-whisper`, which is large).

### 7. Iterate

When you change code locally:

```powershell
git add .
git commit -m "Describe what changed"
git push
```

Streamlit Cloud picks up the push and re-deploys automatically (~30 seconds).

---

## Common gotchas

- **`faster-whisper` model download on first request.** Streamlit Cloud's free instance has limited memory and can be slow to download the model on first transcription. If users complain about a long first transcription, that's why. The `small` model (~470 MB) should fit; `medium` may not.
- **API key not found.** If you see an `AuthenticationError`, double-check the secret name is exactly `ANTHROPIC_API_KEY` in Streamlit Cloud's secrets UI.
- **Re-pushing the same commit.** If `git push` says "everything up-to-date," you haven't actually committed your changes — re-run `git add` + `git commit`.
- **You accidentally committed a secret.** Treat the key as compromised: rotate it immediately on the Anthropic console. Then `git rm --cached <file>` and commit again. The leaked value lives in your git history forever; rotation is the only real fix.
