# SDP Operator
SDP Operator is a Kubernetes operator to configure an Appgate SDP system.

# Table of Contents
* [Getting Started](#getting-started)
  * [Prerequisite](#prerequisite)
  * [Installing the Normal Operator](#installing-the-normal-operator)
  * [Installing the Reverse Operator](#installing-the-reverse-operator)
    * [GitHub](#github)
    * [GitLab](#gitlab)
  * [Installing the Git Operator](#installing-the-git-operator)
* [Examples](#examples)
* [Helm Values](#helm-values)
* [Advanced Usage](#advanced-usage)
  * [External Source for Secrets and Files](#external-source-for-secrets-and-files)
    * [Secret Source](#configuring-an-external-secret-source)
      * [Hashicorp Vault](#vault)
    * [File Source](#configuring-an-external-file-source)
      * [HTTP](#http)
      * [S3](#s3)
  * [Encrypt Secrets with Fernet Key](#encrypt-secrets-with-fernet-key)
  * [CA Certificates](#ca-certificates)
  * [Dump Entities into YAML](#dump-entities-into-yaml)
  * [Validate Entities against OpenAPI Spec](#validate-entities-against-an-openapi-spec)


# Getting Started
## Prerequisite
The following tools are required to install the SDP Operator
* helm v3.8.0+ - https://helm.sh/docs/intro/install/
* kubectl - https://kubernetes.io/docs/tasks/tools/#kubectl

> Browse available versions by navigating to the [SDP Operator Releases](https://github.com/appgate/sdp-operator/releases)

1. Add `appgate/sdp-operator` to your Helm repository
   ```shell
   helm repo add appgate https://appgate.github.io/sdp-operator/
   helm repo update
   ```
2. Install the SDP Operator CRD
   ```shell
   helm install sdp-operator-crd appgate/sdp-operator-crd \
       --namespace sdp-system \
       --create-namespace
   ```

## Installing the Normal Operator
Standard Mode pushes entities on Kubernetes to an Appgate SDP system
1. Create a secret containing Admin API credentials
   ```shell
   kubectl create secret generic sdp-operator-secret \
       --from-literal=appgate-operator-user="<USERNAME>" \
       --from-literal=appgate-operator-password="<PASSWORD>" \
       --namespace sdp-system
   ```

2. Install the SDP Operator in Standard Mode
   ```yaml
   sdp:
     operators:
       - sdp-operator
     sdpOperator:
       version: v18
       host: "https://sdp.appgate.com:8443"
       deviceId: "00000000-1111-2222-3333-44444444"
       secret: sdp-operator-secret
       reverseMode: false
   ```
   ```shell
   helm install normal-operator appgate/sdp-operator --values normal-operator.yaml --namespace sdp-system
   ```

## Installing the Reverse Operator
Reverse Mode pulls SDP entities from an Appgate SDP system into Kubernetes
1. Create a secret containing Admin API credentials
   ```shell
   kubectl create secret generic sdp-operator-secret \
       --from-literal=appgate-operator-user="<USERNAME>" \
       --from-literal=appgate-operator-password="<PASSWORD>" \
       --namespace sdp-system
   ```
2. Install the SDP Operator in Reverse Mode
   ```yaml
   sdp:
     operators:
       - sdp-operator
     sdpOperator:
       version: v18
       host: "https://sdp.appgate.com:8443"
       deviceId: "00000000-1111-2222-3333-44444444"
       secret: sdp-operator-secret
       reverseMode: true
   ```
   ```shell
   helm install reverse-operator appgate/sdp-operator --values reverse-operator.yaml --namespace sdp-system
   ```

## Installing the Git Operator
Git Operator pushes SDP entities on Kubernetes to a Git repository and create pull requests on GitHub or GitLab

### GitHub
1. Create a secret containing SSH key and GitHub token
   ```shell
   # GitHub
   kubectl create secret generic github-operator-secret \
       --from-literal=github-token="<GITHUB_TOKEN>" \
       --from-file=git-ssh-key="<SSH_KEY_PATH>"
   ```
2. Install the Git Operator for GitHub
   ```yaml
   sdp:
     operators:
       - git-operator
     gitOperator:
       version: v18
       secret: github-operator-secret
       git:
         vendor: github
         mainBranch: main
         baseBranch: main
         repository: appgate/github-example
   ```
   ```shell
   helm install github-operator appgate/sdp-operator --values github-operator.yaml --namespace sdp-system
   ```
   
### GitLab
1. Create a secret containing SSH key and GitLab token
   ```shell
   # GitLab
   kubectl create secret generic gitlab-operator-secret \
       --from-literal=gitlab-token="<GITLAB_TOKEN>" \
       --from-file=git-ssh-key="<SSH_KEY_PATH>"
   ```

2. Install the Git Operator for GitLab
   ```yaml
   sdp:
     operators:
       - git-operator
     gitOperator:
       version: v18
       secret: gitlab-operator-secret
       git:
         vendor: gitlab
         mainBranch: main
         baseBranch: main
         repository: appgate/gitlab-example
   ```
   ```shell
   helm install gitlab-operator appgate/sdp-operator --values gitlab-operator.yaml --namespace sdp-system
   ```

# Examples
* [Normal Operator](examples/normal-mode)
* [Reverse Operator](examples/reverse-mode)
* [GitOps with SDP Operator](examples/gitops)
* [Sync from Collective A to Collective B](examples/sync)

# Helm Values
For the list of available Helm parameters, please go to [Helm Values](doc/values.md)

# Advanced Usage
## External Source for Secrets and Files
By design, the Admin API does not return sensitive information and binary data in its response. That means, you cannot sync any entity from Collective A to Collective B if it contains any secret or file fields. 

Suppose you want to sync a LocalUser from Collective A to Collective B. The reverse operator will sync the LocalUser entity from Collective A into Kubernetes without the `password` field (because the response to GET /localuser does not contain such field). If this entity is pushed to Collective B as-is, it would fail because `password` is a required value. To fix this issue, you can configure the normal operator to fetch and load the `password` value in memory before pushing it to Collective B. 

The same logic applies to binary data. DeviceScript is an entity that contains a binary data in field `file`. By configuring an external source for files, you can load the binary data before pushing the entity to target collective.

SDP Operator expects secrets and files to be uploaded to the store in a specific format:
```
{Entity Type}-{API Version}/{Name}/{Key}
```

### Configuring an External Secret Source
The following secret source are supported:
* Hashicorp Vault

#### Vault
Create a secret containing the Vault token
```shell
kubectl create secret generic sdp-operator-vault-secret \
    --from-literal=vault-token="<VAULT_TOKEN>"
```
Install the SDP Operator with Vault
```yaml
sdp:    
  externalSecret:
    enabled: true
    type: vault
    source:
      vault:
        address: "https://vault.example.com:8200"
        tokenSecret: sdp-operator-vault-secret

# Note: Other required helm values are omitted for simplicity
```

SDP Operator expects secrets to be stored under `/data/secret/sdp`

Initialize the `sdp` path by uploading data for v18 LocalUser (username=`john.doe` password=`password123`)
```shell
vault kv put secret/sdp localuser-v18/john.doe/password="password123"
```

On subsequent uploads, you can use `vault kv patch` to update the secret. For example, to upload another v18 LocalUser (username=`jane.doe`, password=`password123`), run the following:
```shell
vault kv patch secret/sdp localuser-v18/jane.doe/password="password123"
```


### Configuring an External File Source
The following external file source are supported:
* HTTP
* S3

#### HTTP
```yaml
sdp:
  externalFile:
    enabled: true
    type: http
    source:
      http:
        address: "https://example.com:8000"

# Note: Other required helm values are omitted for simplicity
```
SDP Operator expects the files to be stored at the root of the filesystem.

Upload the file `example.sh` for v18 DeviceScript under the following path:
```
/devicescript-v18/example/file
```

#### S3
Create secret containing the access key and secret key for the S3 storage
```shell
kubectl create secret generic sdp-operator-s3-secret \
    --from-literal=access-key="<S3_ACCESS_KEY>"
    --from-literal=secret-key="<S3_SECRET_KEY>"
```

Install the SDP Operator with S3
```yaml
sdp:
  externalFile:
    enabled: true
    type: s3
    source:
      s3:
        address: "http://example.com:8000"
        tokenSecret: sdp-operator-http-secret

# Note: Other required helm values are omitted for simplicity
```

SDP Operator expects the files to be stored under bucket `sdp`

Create a bucket `/sdp` on the root of the object store

Upload the file `example.sh` for v18 DeviceScript under the following path:
```
/sdp/devicescript-v18/example/file
```

## Encrypt Secrets with Fernet Key
Sensitive information can be stored in the YAML as encrypted secrets using [fernet (symmetric encryption)](https://cryptography.io/en/latest/fernet/).

To generate a new fernet key, run:
```shell
python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'
```

To generate a secret with the key, run:
```shell
export SECRET="super-sensitive-information"
export KEY="dFVzzjKCa9mWbeig8dprliGLCXwnwE5Fbycz4Xe2ptk="
python3 -c 'from cryptography.fernet import Fernet;import os;print(Fernet(os.getenv("KEY")).encrypt(bytes(os.getenv("SECRET").encode())))'
```

After generating the secret, the encrypted value can be safely stored inside the YAML file as plain-text. When the operator encounters such field, it will read the value of environment variable `APPGATE_OPERATOR_FERNET_KET` to decrypt and read secrets in entities.
```yaml
sdp:
  sdpOperator:
    fernetKey: "dFVzzjKCa9mWbeig8dprliGLCXwnwE5Fbycz4Xe2ptk="
```

## CA Certificates
CA certificate in PEM format can be stored in env `APPGATE_OPERATOR_CACERT`. We recommend storing the contents of the PEM as a base64 encoded string.
```yaml
sdp: 
  sdpOperator:
    caCert: "$(cat cert.ca)"
```

## Dump Entities into YAML
`dump-entities` command will read the entities from an existing SDP system and dump them into YAML.
```shell
$ python3 -m appgate --spec-directory /root/appgate/api_specs/v15 dump-entities
```

The above command will generate a directory that contains the YAML
```shell
$ ls -l example-v15/
total 52
-rw-r--r-- 1 root root 1756 Jul 20 23:03 administrativerole.yaml
-rw-r--r-- 1 root root 3537 Jul 20 23:03 appliance.yaml
-rw-r--r-- 1 root root  143 Jul 20 23:03 clientconnection.yaml
-rw-r--r-- 1 root root  184 Jul 20 23:03 condition.yaml
-rw-r--r-- 1 root root  194 Jul 20 23:03 criteriascripts.yaml
-rw-r--r-- 1 root root  332 Jul 20 23:03 globalsettings.yaml
-rw-r--r-- 1 root root 1405 Jul 20 23:03 identityprovider.yaml
-rw-r--r-- 1 root root  423 Jul 20 23:03 ippool.yaml
-rw-r--r-- 1 root root  251 Jul 20 23:03 localuser.yaml
-rw-r--r-- 1 root root  479 Jul 20 23:03 mfaprovider.yaml
-rw-r--r-- 1 root root 1054 Jul 20 23:03 policy.yaml
-rw-r--r-- 1 root root  695 Jul 20 23:03 ringfencerule.yaml
-rw-r--r-- 1 root root  602 Jul 20 23:03 site.yaml
```

## Validate Entities against an OpenAPI Spec
`validate-entities` command will validate the compatibility of entities against a version of the OpenAPI specification. This is useful for verifying if entities dumped from one SDP system is compatible with another SDP system.

```shell
$ python3 -m appgate --spec-directory /root/appgate/api_specs/v17 validate-entities examples-v15/
```

In the example above, we validated the v15 entities (generated by `dump-entities` command) to a v17 OpenAPI specification. The command will attempt to load all entities defined in `examples-v15-entities/` as a v17 entities, reporting errors if encountered any.


# How It Works
[Custom Resource Definitions (CRD)](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/) on Kubernetes allow the operator to represent Appgate SDP entities as YAMLs. Each instance of an entity is stored as a Custom Resource. The operator reads each instance's spec and syncs the entity with the controller using the Admin API. SDP Operator consumes a version from [Appgate SDP OpenAPI Spec](https://github.com/appgate/sdp-api-specification) to generate entities for a given version of the controller.

For each entity, the operator begins a timer and an event loop to listen for any changes happening on the cluster. Every time an event is received, the timer resets. After the timeout period has expired (in other words, when no event has newly arrived), the operator proceeds to compute a Plan. A Plan represents the difference between the current state on the controller vs the desired state defined in Kubernetes - it outlines what entities will be created/updated/deleted on the controller. After the plan is computed, the operator to execute the Plan on the controller using the API in order to produce the desired state.

It is important to note that, by design, any state defined in Kubernetes wins over state in the SDP system - any external changes made outside the operator will be overwritten. For example, if an administrator makes a change to the Policy via admin UI, the operator will determine the change as 'out-of-sync- and undoes the change.
