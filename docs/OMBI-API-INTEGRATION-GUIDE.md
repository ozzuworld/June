# Ombi API Integration Guide
## Complete Documentation for June Platform Migration

This document provides comprehensive API documentation for migrating from Jellyseerr to Ombi in the June Platform.

## Executive Summary

**Good News**: There is **NO existing Jellyseerr integration** in the June platform backend services. This means:
- ✅ No code to refactor in June services
- ✅ Clean migration path
- ✅ Just need to ensure Ombi is properly configured and accessible
- ✅ Frontend/UI can directly use Ombi's API endpoints

---

## Ombi API Documentation

### Base URL
```
https://ombi.{domain}/api/v1
https://ombi.{domain}/api/v2  (some endpoints)
```

### Authentication

Ombi supports **two authentication methods**:

#### 1. Bearer Token (Recommended for Users)
```http
POST /api/v1/Token
Content-Type: application/json

{
  "username": "admin",
  "password": "password",
  "rememberMe": true
}

Response:
{
  "access_token": "eyJhbGciOiJIUzI1...",
  "expiration": "2024-12-01T00:00:00Z"
}
```

**Usage:**
```http
Authorization: Bearer {access_token}
```

#### 2. API Key (Admin Access)
Found in Ombi Settings → Configuration → API Key

**Usage:**
```http
ApiKey: {your-api-key}
```

**Optional Headers with API Key:**
- `UserName`: Associate request with specific user (must exist)
- `ApiAlias`: Associate with any username (even if doesn't exist)

---

## Core API Endpoints

### 1. Search Endpoints

#### Search Movies
```http
GET /api/v1/Search/movie/{searchTerm}
Authorization: Bearer {token}

Response:
[
  {
    "id": 550,
    "title": "Fight Club",
    "releaseDate": "1999-10-15",
    "overview": "...",
    "posterPath": "/path/to/poster.jpg",
    "theMovieDbId": "550",
    "available": false,
    "requested": false,
    "approved": false
  }
]
```

#### Search TV Shows
```http
GET /api/v2/Search/tv/{searchTerm}
Authorization: Bearer {token}

Response:
[
  {
    "id": 1396,
    "title": "Breaking Bad",
    "firstAired": "2008-01-20",
    "overview": "...",
    "banner": "/path/to/banner.jpg",
    "tvDbId": "81189",
    "available": false,
    "requested": false
  }
]
```

#### Search Music
```http
GET /api/v1/Search/music/artist/{searchTerm}
GET /api/v1/Search/music/album/{searchTerm}
Authorization: Bearer {token}

Response:
[
  {
    "foreignArtistId": "mbid-123",
    "artistName": "Radiohead",
    "overview": "...",
    "banner": "/path/to/image.jpg",
    "monitored": false
  }
]
```

---

### 2. Request Endpoints

#### Request Movie
```http
POST /api/v1/Request/movie
Authorization: Bearer {token}
Content-Type: application/json

{
  "theMovieDbId": 550,
  "languageCode": "en"
}

Response:
{
  "requestId": 123,
  "message": "Movie has been requested successfully",
  "isError": false
}
```

#### Request TV Show
```http
POST /api/v2/Request/tv
Authorization: Bearer {token}
Content-Type: application/json

{
  "tvDbId": 81189,
  "requestAll": false,
  "latestSeason": false,
  "firstSeason": false,
  "seasons": [
    {
      "seasonNumber": 1,
      "episodes": [
        { "episodeNumber": 1 }
      ]
    }
  ]
}

Response:
{
  "requestId": 124,
  "message": "TV Show has been requested successfully",
  "isError": false
}
```

#### Request Music (Album)
```http
POST /api/v1/Request/music
Authorization: Bearer {token}
Content-Type: application/json

{
  "foreignAlbumId": "mbid-album-123",
  "foreignArtistId": "mbid-artist-456"
}

Response:
{
  "requestId": 125,
  "message": "Album has been requested successfully",
  "isError": false
}
```

---

### 3. Get Requests

#### Get All Movie Requests
```http
GET /api/v1/Request/movie
Authorization: Bearer {token}

Response:
[
  {
    "id": 123,
    "theMovieDbId": 550,
    "title": "Fight Club",
    "requestedDate": "2024-11-17T10:00:00Z",
    "requestedUser": {
      "userName": "admin",
      "alias": "Admin User"
    },
    "approved": false,
    "available": false,
    "denied": false,
    "deniedReason": null
  }
]
```

#### Get All TV Requests
```http
GET /api/v1/Request/tv
Authorization: Bearer {token}

Response:
[
  {
    "id": 124,
    "tvDbId": 81189,
    "title": "Breaking Bad",
    "requestedDate": "2024-11-17T10:00:00Z",
    "childRequests": [
      {
        "id": 1,
        "seasonRequests": [
          {
            "seasonNumber": 1,
            "episodes": [...]
          }
        ]
      }
    ],
    "approved": false,
    "available": false
  }
]
```

#### Get All Music Requests
```http
GET /api/v1/Request/music
Authorization: Bearer {token}

Response:
[
  {
    "id": 125,
    "foreignAlbumId": "mbid-123",
    "foreignArtistId": "mbid-456",
    "title": "OK Computer",
    "artistName": "Radiohead",
    "requestedDate": "2024-11-17T10:00:00Z",
    "approved": false,
    "available": false
  }
]
```

---

### 4. Request Management

#### Approve Request
```http
POST /api/v1/Request/movie/approve
Authorization: Bearer {token}
Content-Type: application/json

{
  "id": 123
}

Response:
{
  "isError": false,
  "message": "Request approved successfully"
}
```

#### Deny Request
```http
PUT /api/v1/Request/movie/deny
Authorization: Bearer {token}
Content-Type: application/json

{
  "id": 123,
  "reason": "Not available in your region"
}

Response:
{
  "isError": false,
  "message": "Request denied"
}
```

#### Delete Request
```http
DELETE /api/v1/Request/movie/{requestId}
Authorization: Bearer {token}

Response: 200 OK
```

---

### 5. User Management

#### Create User
```http
POST /api/v1/Identity
Authorization: Bearer {token}
Content-Type: application/json

{
  "userName": "newuser",
  "password": "SecurePassword123!",
  "alias": "New User",
  "emailAddress": "user@example.com",
  "claims": [
    {
      "type": "RequestMovie",
      "value": "true",
      "enabled": true
    },
    {
      "type": "RequestTv",
      "value": "true",
      "enabled": true
    },
    {
      "type": "RequestMusic",
      "value": "true",
      "enabled": true
    }
  ]
}

Response:
{
  "id": "user-guid",
  "userName": "newuser",
  "alias": "New User"
}
```

#### Get User
```http
GET /api/v1/Identity
Headers:
  Authorization: Bearer {token}
  UserName: {username}

Response:
{
  "id": "user-guid",
  "userName": "admin",
  "alias": "Administrator",
  "emailAddress": "admin@example.com",
  "claims": [...]
}
```

#### Update User
```http
PUT /api/v1/Identity
Authorization: Bearer {token}
Content-Type: application/json

{
  "id": "user-guid",
  "userName": "existinguser",
  "alias": "Updated Name",
  "emailAddress": "newemail@example.com",
  "claims": [...]
}

Response: 200 OK
```

---

### 6. Available User Roles/Permissions

```javascript
const OMBI_CLAIMS = {
  // Request Permissions
  "RequestMovie": "Can request movies",
  "RequestTv": "Can request TV shows",
  "RequestMusic": "Can request music",

  // Auto-Approve
  "AutoApproveMovie": "Movies auto-approved",
  "AutoApproveTv": "TV shows auto-approved",
  "AutoApproveMusic": "Music auto-approved",

  // Management
  "Admin": "Full admin access",
  "PowerUser": "Manage users and requests",
  "ManageOwnRequests": "Can delete own requests",

  // Viewing
  "Disabled": "User cannot log in",
  "ReceivesNewsletter": "Gets email newsletters"
};
```

---

### 7. Settings/Configuration

#### Get Ombi Settings
```http
GET /api/v1/Settings/Ombi
Authorization: Bearer {token}

Response:
{
  "collectAnalyticData": false,
  "wizard": false,
  "apiKey": "your-api-key-here",
  "ignoreCertificateErrors": false,
  "baseUrl": "/ombi",
  "doNotSendNotificationsForAutoApprove": false,
  "hideRequestsUsers": false,
  "defaultLanguageCode": "en"
}
```

#### Update Settings
```http
POST /api/v1/Settings/Ombi
Authorization: Bearer {token}
Content-Type: application/json

{
  "collectAnalyticData": false,
  "hideRequestsUsers": true,
  ...
}

Response: 200 OK
```

---

### 8. Notifications & Webhooks

#### Get Webhooks
```http
GET /api/v1/Settings/notifications/webhook
Authorization: Bearer {token}

Response:
[
  {
    "enabled": true,
    "webhookUrl": "https://your-service.com/webhook",
    "notificationTemplates": [
      {
        "notificationType": "NewRequest",
        "enabled": true
      }
    ]
  }
]
```

#### Webhook Payloads

When events occur, Ombi sends:

```json
{
  "notification_type": "NewRequest",
  "subject": "New Movie Request",
  "message": "User 'john' requested 'Fight Club'",
  "image": "https://image.tmdb.org/poster.jpg",
  "media_type": "Movie",
  "requestId": 123,
  "user": "john",
  "title": "Fight Club",
  "imdbid": "tt0137523"
}
```

**Event Types:**
- `NewRequest` - New request submitted
- `RequestApproved` - Request approved
- `RequestDeclined` - Request denied
- `RequestAvailable` - Media now available
- `IssueReport` - User reported issue
- `IssueResolved` - Issue resolved

---

## Integration Examples

### Example: Request Flow

```javascript
// 1. User searches for a movie
const searchResults = await fetch('https://ombi.domain.com/api/v1/Search/movie/fight club', {
  headers: { 'Authorization': `Bearer ${token}` }
});

// 2. User selects movie and requests it
const requestResponse = await fetch('https://ombi.domain.com/api/v1/Request/movie', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    theMovieDbId: 550,
    languageCode: 'en'
  })
});

// 3. Admin approves request
const approveResponse = await fetch('https://ombi.domain.com/api/v1/Request/movie/approve', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    id: 123
  })
});

// 4. Ombi sends to Radarr automatically
// 5. When available, Ombi notifies user via webhook
```

---

## Comparison: Jellyseerr vs Ombi

| Feature | Jellyseerr | Ombi |
|---------|-----------|------|
| Movie Requests | ✅ | ✅ |
| TV Requests | ✅ | ✅ |
| Music Requests | ❌ | ✅ |
| Jellyfin Support | ✅ | ✅ |
| API Version | v1 | v1/v2 |
| Authentication | Bearer Token | Bearer Token + API Key |
| User Management | ✅ | ✅ |
| Webhooks | ✅ | ✅ |
| OIDC/SSO | ✅ (Preview) | ⚠️ (Limited) |

---

## Migration Checklist

### Phase 1: Installation ✅ (DONE)
- [x] Created 08.9a-ombi.sh installation script
- [x] Deployed Ombi to Kubernetes
- [x] Configured ingress at https://ombi.{domain}

### Phase 2: Automation ✅ (DONE)
- [x] Created setup-ombi-wizard.py for automated admin user creation
- [x] Created configure-ombi.py for service connections
- [x] Integrated into 08.11-configure-media.sh
- [x] Connected Jellyfin, Sonarr, Radarr, Lidarr

### Phase 3: Migration Strategy

#### Option A: Keep Both (RECOMMENDED)
- Keep Jellyseerr for Movies/TV (familiar to users)
- Use Ombi for Music requests (unique capability)
- Both work with same backend services

#### Option B: Full Migration to Ombi
1. Update installation orchestrator to skip Jellyseerr
2. Remove 08.9-jellyseerr.sh from PHASES array
3. Update final summary to only show Ombi
4. Keep Jellyseerr automation scripts for existing deployments

### Phase 4: Backend Integration (If Needed)
**Current Status**: No backend integration needed!
- June platform services don't currently integrate with Jellyseerr
- Frontend can directly use Ombi's API endpoints
- No code changes needed in June services

### Phase 5: Documentation
- [ ] Update user documentation to mention Ombi
- [ ] Create API integration guide for developers
- [ ] Document webhook setup for notifications

---

## API Reference Quick Links

- **Swagger UI**: `https://ombi.{domain}/swagger`
- **Official Docs**: https://docs.ombi.app
- **API Info**: https://docs.ombi.app/info/api-information/
- **GitHub**: https://github.com/Ombi-app/Ombi

---

## Conclusion

**Ombi is ready to use!** The installation is complete and fully automated. Since there's no existing Jellyseerr integration in the June platform backend, you have three options:

1. **Keep Both** - Jellyseerr for Movies/TV, Ombi for Music ✅ **CURRENT STATE**
2. **Migrate to Ombi** - Replace Jellyseerr completely
3. **Add Integration** - Build June platform features that use Ombi's API

Let me know which direction you'd like to go!
