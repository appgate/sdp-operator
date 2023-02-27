# Reverse Mode
This example demonstrates the following setup:
* SDP Operator in Reverse Mode dumping entities from SDP into Kubernetes 
* Entities created with tag `reverse-mode` gets dumped into Kubernetes

## Steps
1. Add `appgate/sdp-operator` to your Helm repository
   ```bash
   helm repo add appgate https://appgate.github.io/sdp-operator/
   helm repo update
   ```
2. Install the SDP Operator CRD
   ```bash
   helm install sdp-operator-crd appgate/sdp-operator-crd \
       --namespace sdp-system \
       --create-namespace
   ```

3. Create a secret containing Admin API credentials
   ```bash
   kubectl create secret generic sdp-operator-secret \
       --from-literal=appgate-operator-user="<USERNAME>" \
       --from-literal=appgate-operator-password="<PASSWORD>" \
       --namespace sdp-system
   ```
   
4. Install the SDP Operator with Reverse Mode
   ```bash
   helm install normal-operator appgate/sdp-operator \ 
       --set sdp.sdpOperator.host="<HOST>" \
       --set sdp.sdpOperator.deviceId="<DEVICE_ID>" \
       --values reverse-mode.yaml \
       --namespace sdp-system
   ```

5. Navigate to the SDP Admin UI -> Access -> Policy
6. Create a Policy `example-policy` with tag `reverse-mode`
7. Verify that the Policy `example-policy` appears as a CustomResource on Kubernetes
