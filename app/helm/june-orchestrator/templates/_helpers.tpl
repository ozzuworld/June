{{- define "june-orchestrator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "june-orchestrator.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "june-orchestrator-june-orchestrator" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "june-orchestrator.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ include "june-orchestrator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "june-orchestrator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "june-orchestrator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "june-orchestrator.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{ include "june-orchestrator.fullname" . }}
{{- else -}}
default
{{- end -}}
{{- end -}}
