default: build
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
push:
    podman push registry.wayl.one/shot-scraper-api:$(hatch version)
    podman push registry.wayl.one/shot-scraper-api:latest
run-local:
    shot-scraper-api api run
run:
    podman run --env-file .env -p 5050:5000 registry.wayl.one/shot-scraper-api

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

test:
    /usr/bin/time ./scripts/shot.py \
        "https://waylonwalker.com/archive/" \
        "https://waylonwalker.com/vim/" \
        "https://waylonwalker.com/kedro/" \
        "https://waylonwalker.com/markdown-split-panel/" \
        "https://waylonwalker.com/start/" \
        "https://waylonwalker.com/analytics/" \
        "https://waylonwalker.com/thoughts/" \
        "https://waylonwalker.com/markata/" \
        "https://waylonwalker.com/colophon/" \
        "https://waylonwalker.com/about/" \
        "https://waylonwalker.com/year/" \
        "https://waylonwalker.com/print-in-place-nuts-with-cura/" \
        "https://waylonwalker.com/markata-telescope-picker/" \
        "https://waylonwalker.com/markata-supports-jinja-plugins-0-5-0-dev2/" \
        "https://waylonwalker.com/markata-configure-head/" \
        "https://waylonwalker.com/markata-now-uses-hatch/" \
        "https://waylonwalker.com/markata-0-3-0/" \
        "https://waylonwalker.com/tailwind-aspect/" \
        "https://waylonwalker.com/markdown-it-attrs-with-slashes-dont-work/" \
        "https://waylonwalker.com/vim-date/" \
        "https://waylonwalker.com/convert-markdown-pdf-linux/" \
        "https://waylonwalker.com/diskcache-as-debounce/" \
        "https://waylonwalker.com/vim-gq/" \
        "https://waylonwalker.com/obsidian-image-converter/" \
        "https://waylonwalker.com/dunk-is-my-new-diff-pager/" \
        "https://waylonwalker.com/jpillora-installer-til/" \
        "https://waylonwalker.com/setting-up-nvim-manager-starship-prompt/" \
        "https://waylonwalker.com/argo-serversideapply/" \
        "https://waylonwalker.com/modded-minecraft-in-docker/" \
        "https://waylonwalker.com/emoji-in-headless-chrome-in-docker/" \
        "https://waylonwalker.com/tmux-pop-size/" \
        "https://waylonwalker.com/htmx-request-hide-input/" \
        "https://waylonwalker.com/docker-minecraft-server/" \
        "https://waylonwalker.com/postiz-file-upload/" \
        "https://waylonwalker.com/links-rely-on-color-to-be-distiniquishable/" \
        "https://waylonwalker.com/urllink/" \
        "https://waylonwalker.com/debug-cloudflared-tunnel/" \
        "https://waylonwalker.com/setup-cloudflared-tunnel-on-ubuntu/" \
        "https://waylonwalker.com/price-an-stl-print-on-slant3d/" \
        "https://waylonwalker.com/k3s-config-after-first-install/" \
        "https://waylonwalker.com/slug/" \
        "https://waylonwalker.com/obsidian-new-file/" \
        "https://waylonwalker.com/obsidian-go-to-definition/" \
        "https://waylonwalker.com/obsidian-using-templater-like-copier/" \
        "https://waylonwalker.com/markata-github-pages/" \
        "https://waylonwalker.com/lookatme-slides/" \
        "https://waylonwalker.com/from-markdown-to-blog-with-markata/" \
        "https://waylonwalker.com/convert-mp4-for-twitter-with-ffmpeg/" \
        "https://waylonwalker.com/kind-cluster-with-argo/" \
        "https://waylonwalker.com/install-sealed-secreats-via-manifest/" \
        "https://waylonwalker.com/git-find-deleted-files/" \
        "https://waylonwalker.com/redka-runs-on-sqlite/" \
        "https://waylonwalker.com/how-to-list-sqlite-tables/" \
        "https://waylonwalker.com/python-inline-snapshot/" \
        "https://waylonwalker.com/showmount-e/" \
        "https://waylonwalker.com/k3s-worker/" \
        "https://waylonwalker.com/am-i-vulnerable-to-the-xz-backdoor/" \
        "https://waylonwalker.com/arch-dependencies/" \
        "https://waylonwalker.com/ipython-f2/" \
        "https://waylonwalker.com/sqlite-vacuum/" \
        "https://waylonwalker.com/nvim-stupid-gf-bind/" \
        "https://waylonwalker.com/tailwind-animations/" \
        "https://waylonwalker.com/tailwind-custom-size/" \
        "https://waylonwalker.com/copier-trust/" \
        "https://waylonwalker.com/composing-typer-clis/" \
        "https://waylonwalker.com/fix-npm-global-install-needs-sudo/" \
        "https://waylonwalker.com/darkmode-scrollbars/" \
        "https://waylonwalker.com/jinja-loop-variable-and-htmx/" \
        "https://waylonwalker.com/how-to-kill-ollama-server/" \
        "https://waylonwalker.com/latest-page-in-markata/" \
        "https://waylonwalker.com/github-supports-mermaid/" \
        "https://waylonwalker.com/python-enum/" \
        "https://waylonwalker.com/textual-has-devtools/" \
        "https://waylonwalker.com/python-auto-pdb/" \
        "https://waylonwalker.com/pathlib-read-text/" \
        "https://waylonwalker.com/pytest-mock-basics/" \
        "https://waylonwalker.com/copier-template-variables/" \
        "https://waylonwalker.com/pygame-image-load/" \
        "https://waylonwalker.com/pipx-on-windows/" \
        "https://waylonwalker.com/python-pep-584/" \
        "https://waylonwalker.com/pyenv-first-impressions/" \
        "https://waylonwalker.com/linux-unzip-directory/" \
        "https://waylonwalker.com/kedro-ubuntu-impish/" \
        "https://waylonwalker.com/python-cache-key/" \
        "https://waylonwalker.com/updating-cloudflare-pages-using-the-wrangler-cli/" \
        "https://waylonwalker.com/scheduling-cron-jobs-in-kubernetes/" \
        "https://waylonwalker.com/jinja-macros/" \
        "https://waylonwalker.com/python-scandir-ignores-hidden-directories/" \
        "https://waylonwalker.com/textual-app-devtools/" \
        "https://waylonwalker.com/fastapi-static-content/" \
        "https://waylonwalker.com/tailwind-and-jinja/" \
        "https://waylonwalker.com/ansible-install-fonts/" \
        "https://waylonwalker.com/tmux-copy-mode-binding/" \
        "https://waylonwalker.com/practice-kedro/" \
        "https://waylonwalker.com/python-frontmatter/" \
        "https://waylonwalker.com/linux-swap/" \
        "https://waylonwalker.com/textual-popup-hack/" \
        "https://waylonwalker.com/python-git/" \
        "https://waylonwalker.com/kubebernetes-kustomize-diff/" \
        "https://waylonwalker.com/tailscale-ssh/" \
        "https://waylonwalker.com/arch-remove-orphaned-packages/" \
        "https://waylonwalker.com/fastapi-jinja-url-for-with-query-params/" \
        "https://waylonwalker.com/stripe-cancellations/" \
        "https://waylonwalker.com/kubernetes-kubeseal/" \
        "https://waylonwalker.com/django-rest-framework-getting-started/" \
        "https://waylonwalker.com/animal-well-keyboard/" \
        "https://waylonwalker.com/squoosh-cli/" \
        "https://waylonwalker.com/python-reverse-sluggify/" \
        "https://waylonwalker.com/playerctl-fixes-arch/" \
        "https://waylonwalker.com/sqlmodel-indexes/"

testp:
    /usr/bin/time ./scripts/shot.py \
        "https://waylonwalker.com/archive/" \
        "https://waylonwalker.com/vim/" \
        "https://waylonwalker.com/kedro/" \
        "https://waylonwalker.com/markdown-split-panel/" \
        "https://waylonwalker.com/start/" \
        "https://waylonwalker.com/analytics/" \
        "https://waylonwalker.com/thoughts/" \
        "https://waylonwalker.com/markata/" \
        "https://waylonwalker.com/colophon/" \
        "https://waylonwalker.com/about/" \
        "https://waylonwalker.com/year/" \
        "https://waylonwalker.com/print-in-place-nuts-with-cura/" \
        "https://waylonwalker.com/markata-telescope-picker/" \
        "https://waylonwalker.com/markata-supports-jinja-plugins-0-5-0-dev2/" \
        "https://waylonwalker.com/markata-configure-head/" \
        "https://waylonwalker.com/markata-now-uses-hatch/" \
        "https://waylonwalker.com/markata-0-3-0/" \
        "https://waylonwalker.com/tailwind-aspect/" \
        "https://waylonwalker.com/markdown-it-attrs-with-slashes-dont-work/" \
        "https://waylonwalker.com/vim-date/" \
        "https://waylonwalker.com/convert-markdown-pdf-linux/" \
        "https://waylonwalker.com/diskcache-as-debounce/" \
        "https://waylonwalker.com/vim-gq/" \
        "https://waylonwalker.com/obsidian-image-converter/" \
        "https://waylonwalker.com/dunk-is-my-new-diff-pager/" \
        "https://waylonwalker.com/jpillora-installer-til/" \
        "https://waylonwalker.com/setting-up-nvim-manager-starship-prompt/" \
        "https://waylonwalker.com/argo-serversideapply/" \
        "https://waylonwalker.com/modded-minecraft-in-docker/" \
        "https://waylonwalker.com/emoji-in-headless-chrome-in-docker/" \
        "https://waylonwalker.com/tmux-pop-size/" \
        "https://waylonwalker.com/htmx-request-hide-input/" \
        "https://waylonwalker.com/docker-minecraft-server/" \
        "https://waylonwalker.com/postiz-file-upload/" \
        "https://waylonwalker.com/links-rely-on-color-to-be-distiniquishable/" \
        "https://waylonwalker.com/urllink/" \
        "https://waylonwalker.com/debug-cloudflared-tunnel/" \
        "https://waylonwalker.com/setup-cloudflared-tunnel-on-ubuntu/" \
        "https://waylonwalker.com/price-an-stl-print-on-slant3d/" \
        "https://waylonwalker.com/k3s-config-after-first-install/" \
        "https://waylonwalker.com/slug/" \
        "https://waylonwalker.com/obsidian-new-file/" \
        "https://waylonwalker.com/obsidian-go-to-definition/" \
        "https://waylonwalker.com/obsidian-using-templater-like-copier/" \
        "https://waylonwalker.com/markata-github-pages/" \
        "https://waylonwalker.com/lookatme-slides/" \
        "https://waylonwalker.com/from-markdown-to-blog-with-markata/" \
        "https://waylonwalker.com/convert-mp4-for-twitter-with-ffmpeg/" \
        "https://waylonwalker.com/kind-cluster-with-argo/" \
        "https://waylonwalker.com/install-sealed-secreats-via-manifest/" \
        "https://waylonwalker.com/git-find-deleted-files/" \
        "https://waylonwalker.com/redka-runs-on-sqlite/" \
        "https://waylonwalker.com/how-to-list-sqlite-tables/" \
        "https://waylonwalker.com/python-inline-snapshot/" \
        "https://waylonwalker.com/showmount-e/" \
        "https://waylonwalker.com/k3s-worker/" \
        "https://waylonwalker.com/am-i-vulnerable-to-the-xz-backdoor/" \
        "https://waylonwalker.com/arch-dependencies/" \
        "https://waylonwalker.com/ipython-f2/" \
        "https://waylonwalker.com/sqlite-vacuum/" \
        "https://waylonwalker.com/nvim-stupid-gf-bind/" \
        "https://waylonwalker.com/tailwind-animations/" \
        "https://waylonwalker.com/tailwind-custom-size/" \
        "https://waylonwalker.com/copier-trust/" \
        "https://waylonwalker.com/composing-typer-clis/" \
        "https://waylonwalker.com/fix-npm-global-install-needs-sudo/" \
        "https://waylonwalker.com/darkmode-scrollbars/" \
        "https://waylonwalker.com/jinja-loop-variable-and-htmx/" \
        "https://waylonwalker.com/how-to-kill-ollama-server/" \
        "https://waylonwalker.com/latest-page-in-markata/" \
        "https://waylonwalker.com/github-supports-mermaid/" \
        "https://waylonwalker.com/python-enum/" \
        "https://waylonwalker.com/textual-has-devtools/" \
        "https://waylonwalker.com/python-auto-pdb/" \
        "https://waylonwalker.com/pathlib-read-text/" \
        "https://waylonwalker.com/pytest-mock-basics/" \
        "https://waylonwalker.com/copier-template-variables/" \
        "https://waylonwalker.com/pygame-image-load/" \
        "https://waylonwalker.com/pipx-on-windows/" \
        "https://waylonwalker.com/python-pep-584/" \
        "https://waylonwalker.com/pyenv-first-impressions/" \
        "https://waylonwalker.com/linux-unzip-directory/" \
        "https://waylonwalker.com/kedro-ubuntu-impish/" \
        "https://waylonwalker.com/python-cache-key/" \
        "https://waylonwalker.com/updating-cloudflare-pages-using-the-wrangler-cli/" \
        "https://waylonwalker.com/scheduling-cron-jobs-in-kubernetes/" \
        "https://waylonwalker.com/jinja-macros/" \
        "https://waylonwalker.com/python-scandir-ignores-hidden-directories/" \
        "https://waylonwalker.com/textual-app-devtools/" \
        "https://waylonwalker.com/fastapi-static-content/" \
        "https://waylonwalker.com/tailwind-and-jinja/" \
        "https://waylonwalker.com/ansible-install-fonts/" \
        "https://waylonwalker.com/tmux-copy-mode-binding/" \
        "https://waylonwalker.com/practice-kedro/" \
        "https://waylonwalker.com/python-frontmatter/" \
        "https://waylonwalker.com/linux-swap/" \
        "https://waylonwalker.com/textual-popup-hack/" \
        "https://waylonwalker.com/python-git/" \
        "https://waylonwalker.com/kubebernetes-kustomize-diff/" \
        "https://waylonwalker.com/tailscale-ssh/" \
        "https://waylonwalker.com/arch-remove-orphaned-packages/" \
        "https://waylonwalker.com/fastapi-jinja-url-for-with-query-params/" \
        "https://waylonwalker.com/stripe-cancellations/" \
        "https://waylonwalker.com/kubernetes-kubeseal/" \
        "https://waylonwalker.com/django-rest-framework-getting-started/" \
        "https://waylonwalker.com/animal-well-keyboard/" \
        "https://waylonwalker.com/squoosh-cli/" \
        "https://waylonwalker.com/python-reverse-sluggify/" \
        "https://waylonwalker.com/playerctl-fixes-arch/" \
        "https://waylonwalker.com/sqlmodel-indexes/" \
        --parallel

testdark:
    /usr/bin/time ./scripts/shot.py \
    "https://tailwindcss.com/docs/colors" \
    "https://wyattbubbylee.com/dst-forever-world/" \
    "https://www.youtube.com/watch?v=03KsS09YS4E" \
        --parallel
