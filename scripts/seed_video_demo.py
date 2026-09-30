"""Add one local recording fixture without changing existing accounts/problems.
Run inside the API container with --local-demo; provide a new password on stdin.
This is an explicit operator fixture, not an application endpoint.
"""
import sys
import getpass
from shared.core import SessionLocal, get_storage_testcases
from shared.models import User, Problem, TestCase, Category, Difficulty
from api.app.utils.password_manager import hash as hash_password

if sys.argv[1:] != ["--local-demo"]:
    raise SystemExit("Requires --local-demo; use only in your local recording stack")
password = getpass.getpass("Private demo password: ") if sys.stdin.isatty() else sys.stdin.readline().strip()
if len(password) < 12:
    raise SystemExit("Provide a private demo password of at least 12 characters on stdin")
with SessionLocal() as db:
    if db.query(User).filter_by(username="hyperbyte_demo").first() or db.get(Problem, "EOF001"):
        raise SystemExit("Demo fixture already exists; refusing to overwrite it")
    tag = db.get(Category, "demo")
    if not tag:
        tag = Category(name="Demo", slug="demo")
        db.add(tag)
    problem = Problem(id="EOF001", title="Sum Until EOF", difficulty=Difficulty.EASY,
        description="Read all integers from standard input until the end of the file and print their sum. The integers may span several lines.",
        constraints=["1 to 100 integers", "Each integer is between -1000 and 1000"],
        input_desc="Whitespace-separated integers, ending at EOF.",
        output_desc="One integer: the sum of all input values.",
        sample_io={"1 2 3\n4 5": "15"}, explanation="1 + 2 + 3 + 4 + 5 = 15.",
        time_limit_sec=2, memory_limit_mb=64, visibility=True, tags=[tag])
    db.add(problem)
    db.add(User(username="hyperbyte_demo", email="hyperbyte-demo@example.com", password_hash=hash_password(password)))
    storage = get_storage_testcases()
    for index, (source, expected) in enumerate([(b"1 2 3\n4 5\n", b"15\n"), (b"-10 3\n2\n", b"-5\n"), (b"1000 -1000 7\n", b"7\n")], 1):
        problem.testcases.append(TestCase(input_key=storage.upload_bytes("EOF001", f"{index}.in", source), output_key=storage.upload_bytes("EOF001", f"{index}.out", expected)))
    db.commit()
print("Created EOF001 and ordinary contestant hyperbyte_demo; existing data unchanged.")
