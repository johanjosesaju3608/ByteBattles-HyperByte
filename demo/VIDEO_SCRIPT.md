# HyperByte — TatHack PS4 video script

Target: approximately 6–6½ minutes at 130–140 words per minute with short demo pauses. Rehearse once with a timer; finish between 5:00 and 7:00. Read only the quoted narration below, not the directions. Replace the team name if needed. Use your own voice; this is a script for a real screen recording, not an AI-generated video. Do not claim a live result until it appears.

## 0:00–0:40 — Introduction
Screen: repository README, then local app.

Hello everyone. We are team HyperByte, first-semester computer science students from Amrita Vishwa Vidyapeetham, Amritapuri. For TatHack, we selected problem statement four, ByteBattles.

We started with the supplied competitive-programming platform. Our contribution was to repair its judging and reliability problems, improve security, and build a usable browser interface around the existing backend. We retained the original project attribution. We used AI-assisted development and testing, and this demonstration explains the changes and the evidence behind them.

Our main question was simple: when a student submits a correct program, can the platform judge it correctly and reliably?

## 0:40–1:25 — Architecture
Screen: architecture diagram in README.

The browser sends requests to a FastAPI backend. PostgreSQL stores accounts, problems, submissions, and durable judging jobs. MinIO stores source files and testcases. Redis carries queue notifications to judge workers.

A worker takes a job and runs the submitted code inside Docker sandboxes. C and C++ are compiled once. Each testcase runs in a fresh sandbox, so files and background processes cannot carry over to the next testcase. The final verdict is saved in PostgreSQL and displayed in the browser.

We kept this architecture because the components were already present. We focused on making their interactions more reliable instead of replacing the entire system during the hackathon.

## 1:25–2:25 — Original bugs and diagnosis
Screen: audit/integration-results.jsonl, then audit/FIXES.md. Highlight python_read_until_eof and runtime_units.

We reproduced the original behavior in a separate disposable test environment, so our experiments would not affect existing data.

One important bug involved programs that read input until the end of the file. A correct Python solution using standard input read received Time Limit Exceeded. The input delivery did not provide the expected end-of-file behavior. We changed execution to use a finite input file, allowing the program to finish normally.

We also found a timing conversion error: execution time measured in seconds was being reported incorrectly as milliseconds. We corrected the conversion and checked it with a program that sleeps for about three hundred and fifty milliseconds.

Other findings included broken submission counters, source code accessible without proper authorization, a missing tag-creation endpoint, and a problem with no testcases being accepted. These findings are documented alongside the repaired behavior, so reviewers can compare the before and after results.

## 2:25–3:25 — Reliability and system challenges
Screen: README durable job description, then FIXES verification table.

A bigger system challenge was what happens when a worker crashes or a queue notification is lost. We now save the submission and its judging job together in one database transaction. A dispatcher can resend a notification if necessary.

Workers claim jobs using expiring leases and renew them while running. Each attempt has a unique token. If an old worker returns after another worker has taken over, its result cannot overwrite the newer attempt. Completion and acceptance counting happen together, preventing duplicate notifications from counting a solution twice.

We tested this by killing a busy worker in the disposable environment. The submission recovered and reached Accepted in about thirty-seven seconds.

We also added compilation deadlines, output limits, and per-problem memory enforcement. Missing infrastructure results receive bounded retries rather than remaining pending forever. The sandbox restrictions include disabled networking, a non-root user, and limits on processes and writable storage.

## 3:25–5:25 — Live demonstration
Screen: app, already logged in as hyperbyte_demo. Search Sum Until EOF, click its problem card. Select Python and paste demo/accepted.py.

Now I will demonstrate the repaired submission flow. This problem is called Sum Until EOF. It asks us to read integers across multiple lines and print their sum. The page shows the statement, input and output formats, constraints, example, and resource limits.

I am submitting a short Python solution that reads the entire input until EOF and sums the values. This is the same input-reading pattern that exposed the earlier judging bug. The submission is queued, and the browser follows its status.

[Pause until the verdict appears.]

The result is Accepted. The program finished normally, and its output matched the stored testcases. This demonstrates the EOF repair through the complete browser-to-judge path.

[Paste demo/wrong_answer.py and submit.]

Next, I will submit a program that always prints zero. It is valid Python, but it does not solve this problem. The expected result is Wrong Answer.

[Pause until WA appears.]

The judge reports Wrong Answer, which shows that successful execution alone does not mean acceptance.

[Paste demo/time_limit.py and submit.]

Finally, this program contains an infinite loop. The judge should stop it at the configured time limit rather than letting it run indefinitely.

[Pause until TLE appears, then scroll to submission history.]

The result is Time Limit Exceeded. The history keeps these submissions and lets us reopen their results. We also added problem search, difficulty and tag filters, clearer errors, and automatic session refresh. Administrators have forms for creating tags, uploading problem testcases, and promoting teammates.

## 5:25–6:15 — Evidence and conclusion
Screen: audit/FIXES.md verification table, then repository homepage.

For verification, seventeen focused regression tests passed. We also ran integration checks using the real API, database, storage, and judge. These covered correct C, C++, and Python solutions, incorrect answers, compilation errors, runtime errors, and time and memory limits.

Additional checks covered duplicate jobs, stale worker results, output limits, access permissions, and recovery after worker failure. The repository contains the test scripts and recorded results.

Our scope is a verified local hackathon implementation. We are not claiming production readiness or complete security certification. Public deployment and sustained load testing remain future work.

The main improvement is that ByteBattles now handles the tested judging and failure cases correctly, while giving students and administrators a usable interface. Thank you for watching our submission.
