# Virtual Kubelet Vast.ai Provider
FROM golang:1.21-alpine AS builder

WORKDIR /workspace

# Install dependencies
RUN apk add --no-cache git ca-certificates

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY cmd/ cmd/
COPY pkg/ pkg/

# Build the binary
RUN CGO_ENABLED=0 GOOS=linux go build \
    -ldflags='-s -w -extldflags "-static"' \
    -o virtual-kubelet-vast \
    ./cmd/vk-vast

# Runtime stage
FROM scratch

# Copy CA certificates for HTTPS requests
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

# Copy the binary
COPY --from=builder /workspace/virtual-kubelet-vast /virtual-kubelet-vast

# Health check endpoint
EXPOSE 10255

# Run as non-root user
USER 65534:65534

ENTRYPOINT ["/virtual-kubelet-vast"]
CMD []