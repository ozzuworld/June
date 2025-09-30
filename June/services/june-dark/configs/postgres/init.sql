-- ============================================================================
-- JUNE DARK OSINT FRAMEWORK - PostgreSQL Initialization
-- Control Plane Database Schema
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Crawl targets and configurations
CREATE TABLE IF NOT EXISTS crawl_targets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain VARCHAR(255) NOT NULL UNIQUE,
    target_type VARCHAR(50) NOT NULL, -- 'news', 'forum', 'blog', 'social', 'ct_logs'
    status VARCHAR(20) DEFAULT 'active', -- 'active', 'paused', 'archived'
    priority INTEGER DEFAULT 50, -- 1-100, higher = more important
    crawl_frequency INTERVAL DEFAULT '1 hour',
    last_crawled_at TIMESTAMP,
    next_crawl_at TIMESTAMP,
    crawl_depth INTEGER DEFAULT 2,
    respect_robots BOOLEAN DEFAULT true,
    custom_headers JSONB,
    proxy_pool VARCHAR(50), -- 'default', 'residential', 'datacenter', 'none'
    rate_limit_rpm INTEGER DEFAULT 60, -- requests per minute
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_crawl_targets_status ON crawl_targets(status);
CREATE INDEX idx_crawl_targets_next_crawl ON crawl_targets(next_crawl_at) WHERE status = 'active';
CREATE INDEX idx_crawl_targets_priority ON crawl_targets(priority DESC);

-- Crawl jobs tracking
CREATE TABLE IF NOT EXISTS crawl_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    target_id UUID REFERENCES crawl_targets(id) ON DELETE CASCADE,
    job_type VARCHAR(50) NOT NULL, -- 'scheduled', 'manual', 'retry'
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'running', 'completed', 'failed'
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    pages_crawled INTEGER DEFAULT 0,
    pages_failed INTEGER DEFAULT 0,
    artifacts_collected INTEGER DEFAULT 0,
    error_message TEXT,
    worker_id VARCHAR(100),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_crawl_jobs_status ON crawl_jobs(status);
CREATE INDEX idx_crawl_jobs_target ON crawl_jobs(target_id);
CREATE INDEX idx_crawl_jobs_created ON crawl_jobs(created_at DESC);

-- Artifacts registry
CREATE TABLE IF NOT EXISTS artifacts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES crawl_jobs(id) ON DELETE SET NULL,
    artifact_type VARCHAR(50) NOT NULL, -- 'html', 'pdf', 'image', 'video', 'audio', 'screenshot'
    source_url TEXT NOT NULL,
    minio_path VARCHAR(500) NOT NULL,
    file_size BIGINT,
    file_hash VARCHAR(64), -- SHA-256
    mime_type VARCHAR(100),
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'processing', 'indexed', 'failed'
    enrichment_status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'enriched', 'skipped'
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

CREATE INDEX idx_artifacts_type ON artifacts(artifact_type);
CREATE INDEX idx_artifacts_status ON artifacts(status);
CREATE INDEX idx_artifacts_hash ON artifacts(file_hash);
CREATE INDEX idx_artifacts_created ON artifacts(created_at DESC);

-- Watchlists (for alerts)
CREATE TABLE IF NOT EXISTS watchlists (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    watchlist_type VARCHAR(50) NOT NULL, -- 'domain', 'keyword', 'email', 'phone', 'face', 'pattern'
    pattern TEXT NOT NULL,
    is_regex BOOLEAN DEFAULT false,
    priority VARCHAR(20) DEFAULT 'medium', -- 'low', 'medium', 'high', 'critical'
    alert_enabled BOOLEAN DEFAULT true,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_watchlists_type ON watchlists(watchlist_type);
CREATE INDEX idx_watchlists_priority ON watchlists(priority);
CREATE INDEX idx_watchlists_enabled ON watchlists(alert_enabled) WHERE alert_enabled = true;

-- Alerts
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    watchlist_id UUID REFERENCES watchlists(id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL, -- 'doxx_pattern', 'typosquat', 'face_match', 'keyword_match'
    severity VARCHAR(20) NOT NULL, -- 'low', 'medium', 'high', 'critical'
    title TEXT NOT NULL,
    description TEXT,
    artifact_id UUID REFERENCES artifacts(id) ON DELETE SET NULL,
    source_url TEXT,
    matched_pattern TEXT,
    confidence_score NUMERIC(5,4), -- 0.0000 to 1.0000
    status VARCHAR(20) DEFAULT 'new', -- 'new', 'acknowledged', 'investigating', 'resolved', 'false_positive'
    assigned_to VARCHAR(100),
    resolved_at TIMESTAMP,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_alerts_type ON alerts(alert_type);
CREATE INDEX idx_alerts_severity ON alerts(severity);
CREATE INDEX idx_alerts_status ON alerts(status);
CREATE INDEX idx_alerts_created ON alerts(created_at DESC);
CREATE INDEX idx_alerts_watchlist ON alerts(watchlist_id);

-- System configuration
CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type VARCHAR(50) NOT NULL, -- 'crawl_started', 'alert_created', 'config_changed'
    actor VARCHAR(100), -- 'system', 'user:username', 'service:collector'
    action TEXT NOT NULL,
    resource_type VARCHAR(50),
    resource_id UUID,
    old_value JSONB,
    new_value JSONB,
    ip_address INET,
    user_agent TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_audit_log_type ON audit_log(event_type);
CREATE INDEX idx_audit_log_actor ON audit_log(actor);
CREATE INDEX idx_audit_log_created ON audit_log(created_at DESC);

-- Queue metrics (for monitoring)
CREATE TABLE IF NOT EXISTS queue_metrics (
    id SERIAL PRIMARY KEY,
    queue_name VARCHAR(100) NOT NULL,
    messages_pending INTEGER DEFAULT 0,
    messages_processing INTEGER DEFAULT 0,
    messages_completed INTEGER DEFAULT 0,
    messages_failed INTEGER DEFAULT 0,
    avg_processing_time_ms INTEGER,
    recorded_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_queue_metrics_name ON queue_metrics(queue_name);
CREATE INDEX idx_queue_metrics_recorded ON queue_metrics(recorded_at DESC);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Update updated_at timestamp automatically
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_crawl_targets_updated_at
    BEFORE UPDATE ON crawl_targets
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_watchlists_updated_at
    BEFORE UPDATE ON watchlists
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_system_config_updated_at
    BEFORE UPDATE ON system_config
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- INITIAL DATA
-- ============================================================================

-- Insert default system configuration
INSERT INTO system_config (key, value, description) VALUES
    ('mode', '"day"', 'Operational mode: day (conservative) or night (aggressive)'),
    ('collector_concurrency', '8', 'Number of concurrent crawl workers'),
    ('collector_delay', '1.0', 'Delay between requests in seconds'),
    ('alert_backend', '"kibana"', 'Alert destination: kibana, slack, email, telegram'),
    ('es_retention_days', '90', 'Elasticsearch hot data retention in days'),
    ('offload_enabled', 'false', 'Enable automatic artifact offload to external S3/NAS')
ON CONFLICT (key) DO NOTHING;

-- Insert seed crawl targets (recommended OSINT sources)
INSERT INTO crawl_targets (domain, target_type, priority, crawl_frequency, crawl_depth, metadata) VALUES
    ('thehackernews.com', 'news', 90, '30 minutes', 2, '{"description": "Cybersecurity news", "tags": ["infosec", "threats"]}'),
    ('bleepingcomputer.com', 'news', 90, '30 minutes', 2, '{"description": "Tech and security news", "tags": ["malware", "vulnerabilities"]}'),
    ('krebsonsecurity.com', 'blog', 85, '1 hour', 3, '{"description": "Brian Krebs security blog", "tags": ["investigations", "cybercrime"]}'),
    ('threatpost.com', 'news', 80, '1 hour', 2, '{"description": "Threat intelligence news", "tags": ["vulnerabilities", "exploits"]}'),
    ('securityweek.com', 'news', 75, '2 hours', 2, '{"description": "Enterprise security news", "tags": ["enterprise", "policies"]}')
ON CONFLICT (domain) DO NOTHING;

-- Insert default watchlists for Phase 1 alerts
INSERT INTO watchlists (name, watchlist_type, pattern, is_regex, priority, metadata) VALUES
    ('PII Exposure', 'pattern', 'SSN|Social Security|Credit Card|Driver License', true, 'critical', '{"description": "Detect personal identifiable information"}'),
    ('Typosquatting Domains', 'domain', 'gogle|microsfot|amazn|paypa1', true, 'high', '{"description": "Common typosquatting patterns"}'),
    ('Credential Dumps', 'keyword', 'password dump|leaked credentials|data breach', false, 'high', '{"description": "Potential credential leaks"}'),
    ('Malware Distribution', 'keyword', 'ransomware|trojan|malware sample|exploit kit', false, 'high', '{"description": "Malware-related content"}'),
    ('Threat Actor IOCs', 'pattern', '\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', true, 'medium', '{"description": "IP addresses in content"}')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- VIEWS FOR MONITORING
-- ============================================================================

-- Active crawl jobs summary
CREATE OR REPLACE VIEW v_active_crawl_summary AS
SELECT 
    cj.status,
    COUNT(*) as job_count,
    SUM(cj.pages_crawled) as total_pages,
    SUM(cj.artifacts_collected) as total_artifacts,
    AVG(EXTRACT(EPOCH FROM (COALESCE(cj.completed_at, NOW()) - cj.started_at))) as avg_duration_seconds
FROM crawl_jobs cj
WHERE cj.created_at > NOW() - INTERVAL '24 hours'
GROUP BY cj.status;

-- Alerts summary by severity
CREATE OR REPLACE VIEW v_alerts_summary AS
SELECT 
    severity,
    status,
    COUNT(*) as alert_count,
    MIN(created_at) as oldest_alert,
    MAX(created_at) as newest_alert
FROM alerts
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY severity, status;

-- Storage usage by artifact type
CREATE OR REPLACE VIEW v_storage_summary AS
SELECT 
    artifact_type,
    COUNT(*) as artifact_count,
    SUM(file_size) as total_bytes,
    ROUND(SUM(file_size)::numeric / (1024*1024*1024), 2) as total_gb,
    AVG(file_size) as avg_file_size
FROM artifacts
GROUP BY artifact_type;

-- ============================================================================
-- GRANTS (if using specific application user)
-- ============================================================================

-- If you create a specific app user later:
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO juneapp;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO juneapp;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO juneapp;

-- ============================================================================
-- COMPLETED
-- ============================================================================

-- Log successful initialization
INSERT INTO audit_log (event_type, actor, action, metadata)
VALUES ('database_init', 'system', 'PostgreSQL schema initialized successfully', 
        '{"version": "1.0.0", "timestamp": "' || NOW() || '"}');