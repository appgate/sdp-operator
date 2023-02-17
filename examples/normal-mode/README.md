# Normal Mode
This example demonstrates the following setup:
* SDP Operator in Normal Mode syncing entities on Kubernetes to SDP
* Only entities tagged with `normal-mode` is synced
* Policy `example-policy-1` is synced to the SDP

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
   
4. Install the SDP Operator with Normal Mode
   ```bash
   helm install normal-operator appgate/sdp-operator \ 
       --set sdp.sdpOperator.host="<HOST>" \
       --set sdp.sdpOperator.deviceId="<DEVICE_ID>" \
       --values normal-mode.yaml \
       --namespace sdp-system
   ```

5. Create the Policy entity on Kubernetes
   ```bash
   kubectl apply -f policy.yaml
   ```

6. Navigate to the Admin UI -> Access -> Policy and verify that the policy `example-policy-1` is synced
