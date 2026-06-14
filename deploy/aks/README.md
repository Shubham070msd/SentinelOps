# Running SentinelOps on AKS (portability / Azure story)

Demo on `kind` for reliability; this proves the same manifests run on AKS.

```bash
az group create -n sentinelops-rg -l eastus
az aks create -g sentinelops-rg -n sentinelops-aks --node-count 1 --generate-ssh-keys
az aks get-credentials -g sentinelops-rg -n sentinelops-aks

kubectl apply -f ../demo/memory-hog.yaml      # inject the failure
# build + push the SentinelOps image to ACR, then deploy it as a Deployment + Service
```

The agent uses the in-cluster Kubernetes config automatically when deployed
inside AKS (see `_load()` in the tools).
