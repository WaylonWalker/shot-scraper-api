default: build set-image
fresh: create-ns cred convert deploy viz
update: convert patch

regcred:
    kubectl get secret -n default regcred --output=yaml -o yaml | sed 's/namespace: default/namespace: shot/' | kubectl apply -n shot -f - && echo deployed secret || echo secret exists
build:
    podman build \
        -t registry.wayl.one/shot-scraper-api \
        -t registry.wayl.one/shot-scraper-api:$(hatch version) \
        -f Dockerfile .
    # podman push docker.io/waylonwalker/shot-scraper-api docker.io/waylonwalker/shot-scraper-api:$(hatch version)
    # podman push docker.io/waylonwalker/shot-scraper-api docker.io/waylonwalker/shot-scraper-api:latest
    podman push registry.wayl.one/shot-scraper-api:$(hatch version)
    podman push registry.wayl.one/shot-scraper-api:latest

create-ns:
    kubectl create ns shot && echo created ns shot || echo namespace shot already exists
cred:
    kubectl get secret regcred --output=yaml -o yaml | sed 's/namespace: default/namespace: shot/' | kubectl apply -n shot -f - && echo deployed secret || echo secret exists
convert:
    kompose convert -o deployment.yaml -n shot --replicas 3
deploy:
    kubectl apply -f deployment.yaml
delete:
    kubectl delete all --all -n shot --timeout=0s
viz:
    k8sviz -n shot --kubeconfig $KUBECONFIG -t png -o shot-k8s.png
restart:
    kubectl rollout restart -n shot deployment/shot-wayl-one
patch:
    kubectl patch -f deployment.yaml

describe:
    kubectl get deployment -n shot
    kubectl get rs -n shot
    kubectl get pod -n shot
    kubectl get svc -n shot
    kubectl get ing -n shot


describe-pod:
    kubectl describe pod -n shot

logs:
    kubectl logs --all-containers -l io.kompose.service=shot-wayl-one -n shot -f
