# SkyMaster K8s deployment (v2.1 T2.3)

Production-ready Kubernetes manifests for the SkyMaster drone-management
platform. Uses Kustomize for base/overlay composition rather than Helm
templating — simpler for teams that already have kubectl/kustomize
muscle memory, and avoids yet-another-DSL.

## Layout

```
deploy/k8s/
├── base/                       # everything shared across envs
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secret.example.yaml     # copy → secret.yaml, fill in values
│   ├── api-deployment.yaml     # FastAPI pod(s)
│   ├── worker-deployment.yaml  # GPU worker pod(s)
│   ├── postgres-statefulset.yaml
│   ├── redis-deployment.yaml
│   ├── minio-statefulset.yaml
│   ├── services.yaml
│   ├── ingress.yaml
│   └── kustomization.yaml
├── overlays/
│   ├── dev/                    # minikube / kind, no GPU, replicas=1
│   ├── staging/                # single-node GPU, replicas=2 api / 1 worker
│   └── prod/                   # multi-node GPU, HPA enabled, LB, cert-manager
└── README.md
```

## Prereqs

- Kubernetes 1.28+ (tested on 1.29)
- Kustomize 5.x (`kubectl kustomize` bundled with kubectl 1.27+ works)
- **For GPU workers**: NVIDIA device plugin daemonset installed
  (`nvidia.com/gpu` resource class available on GPU nodes)
- Storage: default StorageClass with WaitForFirstConsumer binding mode
- Ingress: `nginx-ingress` or `traefik` reachable at your cluster edge
- (Prod only) cert-manager for TLS

## Quickstart · dev overlay

```bash
# 1. Fill in the secret template
cp deploy/k8s/base/secret.example.yaml deploy/k8s/base/secret.yaml
$EDITOR deploy/k8s/base/secret.yaml     # set JWT secret + worker token + DB pw

# 2. Apply the dev overlay
kubectl apply -k deploy/k8s/overlays/dev

# 3. Wait for pods
kubectl -n skymaster get pods -w

# 4. Port-forward API for local testing
kubectl -n skymaster port-forward svc/skymaster-api 8000:8000
curl http://localhost:8000/api/v1/health
```

## Prod overlay checklist

- [ ] Update `overlays/prod/kustomization.yaml` `commonLabels` to your org
- [ ] Set correct `image:tag` — never use `latest` in prod
- [ ] Configure `ingress.yaml` host + TLS annotations
- [ ] Point Postgres/Redis to a managed service (AWS RDS / TencentDB) via
      `overlays/prod/external-db.yaml`, remove in-cluster statefulset
- [ ] Set `HorizontalPodAutoscaler` targets per your capacity plan
- [ ] Configure NetworkPolicies to whitelist ingress traffic
- [ ] Enable PodDisruptionBudgets on api + worker

## Worker scheduling

The worker deployment declares `nvidia.com/gpu: 1` in its `resources`.
On GPU-less nodes, kube-scheduler will refuse to place worker pods —
this is intentional. Attach a toleration + nodeSelector matching your
GPU node pool if you use taints.

```yaml
nodeSelector:
  cloud.provider/gpu-type: "a100-40gb"
tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
```

## Scaling model

| Component | Scaling knob | Notes |
|---|---|---|
| API pod | HPA on CPU (target 60%) | Stateless, JWT-based auth |
| Worker pod | Manual replicas OR HPA on custom `queue_length` metric | GPU-bound — one job at a time per pod |
| Postgres | Vertical (bigger node) or migrate to managed | Single-writer |
| Redis | Only for hot cache; MO-lite mode is fine | Job queue is Postgres, not Redis |
| MinIO | Add nodes for horizontal capacity | S3-compatible object storage |

## Deleting

```bash
kubectl delete -k deploy/k8s/overlays/dev
# Note: PVCs are NOT deleted (StorageClass default). Delete manually if needed:
kubectl -n skymaster delete pvc --all
```
