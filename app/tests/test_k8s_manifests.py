"""deploy/k8s 매니페스트의 문법과 스펙 5-2·5-5 의 핵심 값. kubectl 없이 YAML 만 읽는다."""
import pathlib

import yaml

K8S = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "k8s"


def load(name):
    return [d for d in yaml.safe_load_all((K8S / name).read_text(encoding="utf-8")) if d]


def test_httproute_targets_ui_on_traefik_gateway():
    (route,) = load("httproute.yaml")
    assert route["kind"] == "HTTPRoute" and route["metadata"]["namespace"] == "nhn-docs-bot"
    assert route["spec"]["hostnames"] == ["nhn-docs-bot.180-210-89-135.nip.io"]
    parent = route["spec"]["parentRefs"][0]
    assert (parent["name"], parent["namespace"]) == ("traefik-gateway", "traefik")
    backend = route["spec"]["rules"][0]["backendRefs"][0]
    assert (backend["name"], backend["port"]) == ("ui", 8501)


def test_httproute_file_documents_auth_hook():
    text = (K8S / "httproute.yaml").read_text(encoding="utf-8")
    assert "basicAuth" in text and "ExtensionRef" in text


def test_rbac_lets_refresh_restart_ui_only():
    docs = {d["kind"]: d for d in load("rbac.yaml")}
    assert docs["ServiceAccount"]["metadata"]["name"] == "refresh"
    rule = docs["Role"]["rules"][0]
    assert rule["apiGroups"] == ["apps"] and rule["resources"] == ["deployments"]
    assert sorted(rule["verbs"]) == ["get", "patch"]
    assert docs["RoleBinding"]["subjects"][0]["name"] == "refresh"
    assert docs["RoleBinding"]["roleRef"]["name"] == docs["Role"]["metadata"]["name"]


def test_cronjob_schedule_and_ordering():
    (cj,) = load("refresh-cronjob.yaml")
    spec = cj["spec"]
    assert cj["kind"] == "CronJob" and cj["metadata"]["name"] == "refresh"
    assert spec["schedule"] == "0 3 1 * *" and spec["timeZone"] == "Asia/Seoul"
    assert spec["concurrencyPolicy"] == "Forbid"
    assert spec["successfulJobsHistoryLimit"] == 3 and spec["failedJobsHistoryLimit"] == 3
    job = spec["jobTemplate"]["spec"]
    assert job["backoffLimit"] == 0
    pod = job["template"]["spec"]
    assert pod["enableServiceLinks"] is False
    assert pod["serviceAccountName"] == "refresh"
    assert pod["imagePullSecrets"] == [{"name": "regcred"}]
    assert [c["name"] for c in pod["initContainers"]] == ["fix-perms", "crawl", "ingest"]
    assert [c["name"] for c in pod["containers"]] == ["restart"]


def test_cronjob_crawl_and_ingest_details():
    (cj,) = load("refresh-cronjob.yaml")
    pod = cj["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    inits = {c["name"]: c for c in pod["initContainers"]}
    crawl = inits["crawl"]
    assert "nhn-docs-crawler" in crawl["image"]
    assert crawl["args"] == ["--changed", "--save-dir", "/docs"]
    assert crawl["resources"]["requests"]["memory"] == "1Gi" and crawl["resources"]["limits"]["memory"] == "3Gi"
    assert crawl["resources"]["requests"]["cpu"] == "500m" and crawl["resources"]["limits"]["cpu"] == "2"
    mount = crawl["volumeMounts"][0]
    assert mount["mountPath"] == "/docs" and not mount.get("readOnly", False)
    ingest = inits["ingest"]
    assert "nhn-docs-bot" in ingest["image"]
    assert ingest["command"] == ["python", "-u", "ingest.py"] and ingest["args"] == ["--docs-dir", "/docs"]
    env = {e["name"]: e for e in ingest["env"]}
    assert env["DB_PORT"]["value"] == "5432"
    assert env["NVIDIA_API_KEY"]["valueFrom"]["secretKeyRef"] == {"name": "llm", "key": "NVIDIA_API_KEY"}
    restart = pod["containers"][0]
    assert "kubectl" in restart["image"]
    assert "rollout" in " ".join(restart.get("args") or restart.get("command"))
    assert pod["securityContext"]["runAsUser"] == 1000
    assert inits["fix-perms"]["securityContext"]["runAsUser"] == 0


def test_no_secret_values_in_manifests():
    for f in K8S.glob("*.yaml"):
        text = f.read_text(encoding="utf-8")
        assert "nvapi-" not in text, f
        assert "kind: Secret" not in text, f
