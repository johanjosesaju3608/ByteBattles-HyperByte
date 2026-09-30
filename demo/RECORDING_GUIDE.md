# Recording walkthrough

1. Start Docker Desktop and the app with `docker compose up -d`. Open http://127.0.0.1:8000/app.
2. The prepared local fixture is problem **EOF001 — Sum Until EOF**, with three testcases and an ordinary contestant **hyperbyte_demo**. Its private password is in `.env.demo` in your local project. This file is ignored by Git; never show it in the recording. Sign in before recording. This account is not an administrator.
3. Open these tabs: repository README, app, and `audit/FIXES.md`. Open the three small Python files in `demo/` so copying is easy.
4. On macOS, press Shift–Command–5, choose a screen region, enable your microphone in Options, then start recording. Record your own voice. No synthetic voice or generated presenter is needed.
5. Follow [VIDEO_SCRIPT.md](VIDEO_SCRIPT.md). Its timestamps are pacing targets, not guarantees: do one timed rehearsal. Aim for 6:00–6:30 and keep the final file between 5 and 7 minutes.
6. In the live section: search **Sum Until EOF**, click the problem, select **Python**, submit `accepted.py` → AC; submit `wrong_answer.py` → WA; submit `time_limit.py` → TLE. Pause narration briefly for each real verdict. Show the history. Do not run the crash-injection tests during recording.
7. If a verdict takes longer than expected, wait or use Check again. Do not describe an expected verdict as a result until it appears. If necessary, re-record after checking the app; the recorded verification evidence is available separately.
8. Stop recording. Replay the video to check sound, readable text, duration, and absence of secrets. Upload using the organisers' submission instructions. Include the repository link and GitHub IDs of all four teammates.

## Optional C++ demonstration

Use `accepted.cpp` with language C++ if time allows. Skip this extra submission if the video would exceed seven minutes.

## New installation: prepare the fixture

The local database is not committed. On a new installation, after following SETUP.md, run `scripts/seed_video_demo.py` inside the API container with `--local-demo`, passing a private password on standard input. For example, copy the script into the container, then run it interactively:

```sh
docker compose cp scripts/seed_video_demo.py api:/tmp/seed_video_demo.py
docker compose exec api sh -c 'PYTHONPATH=/src .venv/bin/python /tmp/seed_video_demo.py --local-demo'
```

Check your container working directory in the Dockerfile if using a custom image. The script prompts for a hidden password of at least 12 characters and refuses to overwrite an existing demo account or problem. Do this before recording. The fixture script directly seeds local demo data as an operator action; normal problem creation uses the admin website/API.

## Having Codex operate the walkthrough

Codex can click through the real app and submit the prepared examples while you record and narrate. Start the screen recorder yourself and say which section to begin. Use short cues such as “show architecture”, “submit correct solution”, “submit wrong answer”, and “show history” to keep actions synchronized with your voice. This creates a recording of the working application; it does not generate a video or narration. You remain responsible for understanding and explaining the implementation.
