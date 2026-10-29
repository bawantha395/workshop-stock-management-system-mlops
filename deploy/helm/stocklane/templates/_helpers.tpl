{{/* Labels every Stocklane object carries. */}}
{{- define "stocklane.labels" -}}
stocklane.io/environment: {{ .Values.environment }}
{{- end }}

{{/* Restricted pod security context: non-root, seccomp default. */}}
{{- define "stocklane.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{/* Restricted container security context: no privilege escalation, read-only root, no capabilities. */}}
{{- define "stocklane.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop:
  - ALL
{{- end }}

{{/* Changes whenever the shared configuration changes, so pods roll when it does. */}}
{{- define "stocklane.configChecksum" -}}
{{ toJson .Values.config | sha256sum }}
{{- end }}

{{/* Reads platform-config and the service's own secret. */}}
{{- define "stocklane.envFrom" -}}
- configMapRef:
    name: platform-config
- secretRef:
    name: {{ . }}-secrets
{{- end }}
