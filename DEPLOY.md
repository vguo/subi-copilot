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

### 2b. Verify `requirements.txt` exists

Streamlit Cloud's installer reads `requirements.txt` to install dependencies. If you only ship `pyproject.toml`, Streamlit Cloud falls back to Poetry, which fails on this repo with `No file/folder found for package sub-i-copilot` (the package name has hyphens but the actual code lives in `src/`; Poetry can't reconcile that).

Confirm `requirements.txt` is in the repo root and contains at minimum:

```
anthropic>=0.40.0
pydantic>=2.0
python-dotenv>=1.0
faster-whisper>=1.0
streamlit>=1.30
```

You keep `pyproject.toml` *too* — that's what `pip install -e .` reads for local development. The two files coexist on purpose: `pyproject.toml` is for editable installs locally, `requirements.txt` is what Streamlit Cloud actually uses to build the environment.

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
4. Click "Advanced settings" → "Secrets". Paste **at least one** of these (whichever providers you plan to use):

   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   GEMINI_API_KEY = "AIza..."
   ```

   - **`ANTHROPIC_API_KEY`** — required if you'll use the Claude provider (sidebar default). Get one at <https://console.anthropic.com/>.
   - **`GEMINI_API_KEY`** — required if you'll use the Gemini provider (free tier). Get one at <https://aistudio.google.com/apikey>.

   You can paste both; the app's sidebar selector chooses which one is actually called at extraction time. Streamlit Cloud encrypts these and exposes them as `st.secrets`. `app.py` bridges them into `os.environ` so the underlying SDKs find them.

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

- **Streamlit Cloud build fails with `No file/folder found for package sub-i-copilot`.** Your repo is missing `requirements.txt`. See §2b above. Streamlit Cloud falls back to Poetry when only `pyproject.toml` is present, and Poetry can't install this package because the name uses hyphens while the code lives in `src/`. Adding `requirements.txt` sidesteps the project-install dance entirely.
- **`faster-whisper` model download on first request.** Streamlit Cloud's free instance has limited memory and can be slow to download the model on first transcription. If users complain about a long first transcription, that's why. The `small` model (~470 MB) should fit; `medium` may not.
- **API key not found.** If you see an `AuthenticationError` or `RuntimeError: GEMINI_API_KEY not set`, double-check the secret name in Streamlit Cloud's secrets UI matches exactly: `ANTHROPIC_API_KEY` for Claude, `GEMINI_API_KEY` for Gemini. The provider toggle in the sidebar tells you which key the app is trying to use.
- **`StreamlitSecretNotFoundError` running locally.** `app.py` reads `st.secrets` for the Anthropic key on Streamlit Cloud; locally there's no `secrets.toml`, and any access (including `"KEY" in st.secrets`) raises. The bridge code in `app.py` already wraps this in `try/except` — if you ever touch that block, keep the wrapper.
- **Re-pushing the same commit.** If `git push` says "everything up-to-date," you haven't actually committed your changes — re-run `git add` + `git commit`.
- **You accidentally committed a secret.** Treat the key as compromised: rotate it immediately on the Anthropic console. Then `git rm --cached <file>` and commit again. The leaked value lives in your git history forever; rotation is the only real fix.
- **GitHub repo under a lab/org account.** Create the repo under your *personal* account, not under any organization you're a member of. Streamlit Cloud's OAuth asks for visibility into your orgs but only pulls code from the specific repo you point it at. Personal-account repo = no org notifications, no risk of cross-contaminating the lab's repos.
