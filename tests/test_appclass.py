"""Tests for spindle.appclass — classify (pure) + signal adapters (I/O)."""

from __future__ import annotations

import json

import spindle.appclass as ac


# ---- pure classifier ----------------------------------------------------

def test_classify_llm_service():
    sig = ac.RepoSignal(
        name="somm", language="python",
        deps=frozenset({"fastapi", "anthropic"}),
        files=frozenset({"Dockerfile"}),
        registry_kind="service",
    )
    cls = ac.classify(sig)
    assert cls.uses_llms is True
    assert cls.network_service is True
    assert cls.frontend is False
    assert "uses-llms" in cls.tags
    assert "network-service" in cls.tags
    assert cls.cluster_key() == "|".join(sorted(cls.tags))


def test_classify_frontend_typescript():
    sig = ac.RepoSignal(name="web", language="typescript",
                        deps=frozenset({"react", "next"}))
    cls = ac.classify(sig)
    assert cls.frontend is True
    assert cls.uses_llms is False
    assert "lang:typescript" in cls.tags


def test_classify_mcp_from_name():
    sig = ac.RepoSignal(name="sample-mcp", language="python", deps=frozenset())
    assert ac.classify(sig).is_mcp is True


def test_classify_mcp_from_dep():
    sig = ac.RepoSignal(name="thing", language="python", deps=frozenset({"mcp"}))
    assert ac.classify(sig).is_mcp is True


def test_classify_agent_instrumented():
    sig = ac.RepoSignal(name="x", files=frozenset({"CLAUDE.md"}))
    assert ac.classify(sig).agent_instrumented is True


def test_classify_somm_dir_means_llms():
    sig = ac.RepoSignal(name="x", files=frozenset({".somm"}))
    assert ac.classify(sig).uses_llms is True


def test_classify_service_from_registry_kind():
    sig = ac.RepoSignal(name="x", registry_kind="service")
    assert ac.classify(sig).network_service is True


def test_cluster_key_groups_identical_characteristics():
    a = ac.classify(ac.RepoSignal(name="a", language="python", deps=frozenset({"anthropic"})))
    b = ac.classify(ac.RepoSignal(name="b", language="python", deps=frozenset({"openai"})))
    # Different LLM deps, same characteristics → same cluster
    assert a.cluster_key() == b.cluster_key()


# ---- dep normalization --------------------------------------------------

def test_norm_dep_strips_version_and_extras():
    assert ac._norm_dep("anthropic>=0.40") == "anthropic"
    assert ac._norm_dep("uvicorn[standard]") == "uvicorn"
    assert ac._norm_dep("React") == "react"
    assert ac._norm_dep("pytest ; python_version>'3.10'") == "pytest"


def test_norm_dep_keeps_scoped_npm_name():
    assert ac._norm_dep("@angular/core") == "@angular/core"


# ---- signal_from_repo (I/O) ---------------------------------------------

def test_signal_from_repo_python_llm(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["fastapi>=0.1", "anthropic"]\n'
    )
    (tmp_path / "CLAUDE.md").write_text("# agents\n")
    sig = ac.signal_from_repo(tmp_path, name="x", registry_kind="service")
    assert sig.language == "python"
    assert "anthropic" in sig.deps and "fastapi" in sig.deps
    cls = ac.classify(sig)
    assert cls.uses_llms and cls.network_service and cls.agent_instrumented


def test_signal_from_repo_typescript_frontend(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "dependencies": {"react": "^18", "next": "^14"},
        "devDependencies": {"typescript": "^5"},
    }))
    sig = ac.signal_from_repo(tmp_path)
    assert sig.language == "typescript"
    assert ac.classify(sig).frontend is True


def test_signal_from_repo_unknown_when_empty(tmp_path):
    sig = ac.signal_from_repo(tmp_path, name="bare")
    assert sig.language == "unknown"
    assert sig.deps == frozenset()


# ---- signal_from_derive (adapter) ---------------------------------------

def test_signal_from_derive_extracts_language_and_agents():
    derive = {
        "repo_path": "/home/x/projects/sample-app",
        "git": {"branch": "main"},
        "artifacts": [
            {"label": "build", "present": True, "path": "pyproject.toml"},
            {"label": "agents", "present": True, "path": "CLAUDE.md"},
            {"label": "readme", "present": False, "path": None},
        ],
    }
    sig = ac.signal_from_derive(derive, deps={"anthropic"})
    assert sig.name == "sample-app"
    assert sig.language == "python"
    assert "claude.md" in sig.files
    cls = ac.classify(sig)
    assert cls.uses_llms is True and cls.agent_instrumented is True


def test_signal_from_derive_without_deps_is_still_usable():
    derive = {
        "repo_path": "/x/web",
        "artifacts": [{"label": "build", "present": True, "path": "package.json"}],
    }
    sig = ac.signal_from_derive(derive)
    assert sig.language == "javascript"
    assert sig.deps == frozenset()  # deps not in derive output; classifier just sees fewer signals
