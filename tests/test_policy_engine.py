"""Tests for the policy engine."""


from app.integrations.base import DiffHunk
from app.services.diff_parser import tokenize_hunks
from app.services.policy_engine import (
    _apply_builtin_forbidden_apis,
    _apply_builtin_secret_detection,
    _file_matches_glob,
)


class TestBuiltinSecretDetection:
    def test_detects_api_key(self):
        hunk = DiffHunk(
            file_path="config.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+api_key = 'abcdefghijklmnop1234'"
        )
        tokenized = tokenize_hunks([hunk])
        violations = _apply_builtin_secret_detection(tokenized[0])
        assert len(violations) > 0
        assert violations[0].severity == "BLOCKER"

    def test_detects_password(self):
        hunk = DiffHunk(
            file_path="settings.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+password = 'mysecretpassword'"
        )
        tokenized = tokenize_hunks([hunk])
        violations = _apply_builtin_secret_detection(tokenized[0])
        assert len(violations) > 0

    def test_detects_private_key(self):
        hunk = DiffHunk(
            file_path="certs.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+key = '-----BEGIN RSA PRIVATE KEY-----'"
        )
        tokenized = tokenize_hunks([hunk])
        violations = _apply_builtin_secret_detection(tokenized[0])
        assert len(violations) > 0
        assert any(v.rule_type == "secret_detection" for v in violations)

    def test_detects_github_token(self):
        hunk = DiffHunk(
            file_path="ci.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+token = 'ghp_abcdefghijklmnopqrstuvwxyz0123456789'"
        )
        tokenized = tokenize_hunks([hunk])
        violations = _apply_builtin_secret_detection(tokenized[0])
        assert len(violations) > 0

    def test_no_false_positive_on_clean_code(self):
        hunk = DiffHunk(
            file_path="app.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content=(
                "+def get_user(user_id: int):\n"
                "+    return db.query(User).filter_by(id=user_id).first()"
            )
        )
        tokenized = tokenize_hunks([hunk])
        violations = _apply_builtin_secret_detection(tokenized[0])
        assert len(violations) == 0


class TestBuiltinForbiddenApis:
    def test_detects_eval(self):
        hunk = DiffHunk(
            file_path="app.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+result = eval(user_input)"
        )
        tokenized = tokenize_hunks([hunk])
        violations = _apply_builtin_forbidden_apis(tokenized[0])
        assert len(violations) > 0
        assert any("eval" in v.message.lower() for v in violations)

    def test_detects_exec(self):
        hunk = DiffHunk(
            file_path="app.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+exec(code_string)"
        )
        tokenized = tokenize_hunks([hunk])
        violations = _apply_builtin_forbidden_apis(tokenized[0])
        assert len(violations) > 0

    def test_detects_os_system(self):
        hunk = DiffHunk(
            file_path="deploy.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+os.system('rm -rf /')"
        )
        tokenized = tokenize_hunks([hunk])
        violations = _apply_builtin_forbidden_apis(tokenized[0])
        assert len(violations) > 0

    def test_detects_shell_true(self):
        hunk = DiffHunk(
            file_path="build.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+subprocess.run(cmd, shell=True)"
        )
        tokenized = tokenize_hunks([hunk])
        violations = _apply_builtin_forbidden_apis(tokenized[0])
        assert len(violations) > 0

    def test_detects_pickle(self):
        hunk = DiffHunk(
            file_path="data.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+data = pickle.load(f)"
        )
        tokenized = tokenize_hunks([hunk])
        violations = _apply_builtin_forbidden_apis(tokenized[0])
        assert len(violations) > 0

    def test_clean_code_no_violations(self):
        hunk = DiffHunk(
            file_path="app.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+user = User(name='test', email='test@test.com')"
        )
        tokenized = tokenize_hunks([hunk])
        violations = _apply_builtin_forbidden_apis(tokenized[0])
        assert len(violations) == 0


class TestFileMatchesGlob:
    def test_matches_python_files(self):
        assert _file_matches_glob("app/main.py", "*.py")

    def test_matches_wildcard(self):
        assert _file_matches_glob("anything.js", "*")

    def test_none_glob_matches_all(self):
        assert _file_matches_glob("any/file.txt", None)

    def test_no_match(self):
        assert not _file_matches_glob("app/main.py", "*.js")
