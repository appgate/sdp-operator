{{/*
Expand the name of the chart.
*/}}
{{- define "sdp-operator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "sdp-operator.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "sdp-operator.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "sdp-operator.labels" -}}
helm.sh/chart: {{ include "sdp-operator.chart" . }}
{{ include "sdp-operator.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "sdp-operator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sdp-operator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount
*/}}
{{- define "sdp-operator.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "sdp-operator.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Operator Secrets
*/}}
{{- define "sdp-operator.secret" -}}
{{- printf "sdp-operator-secret-%s" .Release.Name }}
{{- end }}

{{/*
Operator Config
*/}}
{{- define "sdp-operator.config" -}}
{{- printf "sdp-operator-config-%s" .Release.Name }}
{{- end }}

{{/*
Operator Metadata Config
*/}}
{{- define "sdp-operator.config-mt" -}}
{{- printf "sdp-operator-config-mt-%s" .Release.Name }}
{{- end }}

{{/*
Operator Role
*/}}
{{- define "sdp-operator.role" -}}
{{- printf "role-%s" .Release.Name }}
{{- end }}

{{/*
Operator RoleBinding
*/}}
{{- define "sdp-operator.rolebinding" -}}
{{- printf "rolebinding-%s" .Release.Name }}
{{- end }}
