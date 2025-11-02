#!/usr/bin/env python3
"""
Phase 1 Testing Script - Verify Clean Architecture

This script tests the Phase 1 refactor to ensure:
1. Clean architecture components work
2. Backward compatibility is maintained
3. Core functionality remains intact
"""

import sys
import asyncio
from datetime import datetime


def test_imports():
    """Test that all new imports work"""
    print("🗋 Testing Phase 1 imports...")
    
    try:
        # Test new clean models
        from app.models.domain import Session, Message, SkillSession, SessionStats
        print("✅ Clean domain models imported")
        
        # Test dependency injection
        from app.core.dependencies import get_session_service, get_livekit_client
        print("✅ Dependency injection imported")
        
        # Test services
        from app.services.session.service import SessionService
        from app.services.external.livekit import LiveKitClient
        print("✅ Clean services imported")
        
        # Test backward compatibility
        from app.session_manager_v2 import session_manager
        print("✅ Backward compatible session manager imported")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False


def test_domain_models():
    """Test the clean domain models"""
    print("🏠 Testing domain models...")
    
    try:
        from app.models.domain import Session, Message, SkillSession
        
        # Test Session creation
        session = Session.create("test-user", "test-room")
        assert session.user_id == "test-user"
        assert session.room_name == "test-room"
        assert len(session.messages) == 0
        print(f"✅ Session model: {session.id[:8]}...")
        
        # Test message addition
        session.add_message("user", "Hello world", {"test": True})
        assert len(session.messages) == 1
        assert session.message_count == 1
        print("✅ Message addition works")
        
        # Test skill session
        session.skill_session.activate_skill("test-skill")
        assert session.skill_session.is_active()
        assert session.skill_session.active_skill == "test-skill"
        print("✅ Skill session works")
        
        return True
        
    except Exception as e:
        print(f"❌ Domain model test failed: {e}")
        return False


def test_session_service():
    """Test the SessionService"""
    print("🛠️ Testing SessionService...")
    
    try:
        from app.core.dependencies import get_session_service
        
        service = get_session_service()
        
        # Test session creation
        session = service._create_session("test-user-2", "test-room-2")
        assert session.user_id == "test-user-2"
        assert session.room_name == "test-room-2"
        print(f"✅ SessionService created session: {session.id[:8]}...")
        
        # Test session retrieval
        retrieved = service.get_session(session.id)
        assert retrieved is not None
        assert retrieved.id == session.id
        print("✅ Session retrieval works")
        
        # Test room mapping
        room_session = service.get_session_by_room("test-room-2")
        assert room_session is not None
        assert room_session.id == session.id
        print("✅ Room mapping works")
        
        # Test message addition
        service.add_message(session.id, "user", "Test message", {"test": True})
        updated_session = service.get_session(session.id)
        assert len(updated_session.messages) == 1
        print("✅ Message addition through service works")
        
        # Test stats
        stats = service.get_stats()
        assert stats.active_sessions >= 1
        print(f"✅ Stats: {stats.active_sessions} active sessions")
        
        return True
        
    except Exception as e:
        print(f"❌ SessionService test failed: {e}")
        return False


def test_backward_compatibility():
    """Test backward compatibility with original interface"""
    print("🔄 Testing backward compatibility...")
    
    try:
        from app.session_manager_v2 import session_manager
        
        # Test the original interface
        session = session_manager.get_or_create_session_for_room("compat-room", "compat-user")
        
        # Test original properties
        assert hasattr(session, 'session_id')
        assert hasattr(session, 'user_id')
        assert hasattr(session, 'room_name')
        assert hasattr(session, 'conversation_history')
        assert hasattr(session, 'skill_session')
        print("✅ Original session interface preserved")
        
        # Test original methods
        session.add_message("user", "Compatibility test", {"compat": True})
        history = session.get_recent_history()
        assert len(history) >= 1
        print("✅ Original methods work")
        
        # Test manager methods
        session_manager.add_to_history(session.session_id, "assistant", "Response", {"test": True})
        stats = session_manager.get_stats()
        assert "active_sessions" in stats
        assert "total_messages" in stats
        print("✅ Original manager interface works")
        
        # Test to_dict (for API responses)
        session_dict = session.to_dict()
        required_fields = ["session_id", "user_id", "room_name", "created_at", "skill_state"]
        for field in required_fields:
            assert field in session_dict, f"Missing field: {field}"
        print("✅ Session serialization works")
        
        return True
        
    except Exception as e:
        print(f"❌ Backward compatibility test failed: {e}")
        return False


def test_dependency_injection():
    """Test dependency injection system"""
    print("🕹️ Testing dependency injection...")
    
    try:
        from app.core.dependencies import get_session_service, get_livekit_client, get_config
        
        # Test singleton behavior
        service1 = get_session_service()
        service2 = get_session_service()
        assert service1 is service2, "SessionService should be singleton"
        print("✅ SessionService singleton works")
        
        # Test configuration injection
        config = get_config()
        assert hasattr(config, 'ai')
        assert hasattr(config, 'services')
        assert hasattr(config, 'livekit')
        print("✅ Configuration injection works")
        
        # Test LiveKit client (might fail if env vars not set, that's ok)
        try:
            livekit_client = get_livekit_client()
            assert hasattr(livekit_client, 'generate_access_token')
            print("✅ LiveKit client injection works")
        except Exception as e:
            print(f"⚠️ LiveKit client test skipped (config issue): {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Dependency injection test failed: {e}")
        return False


def main():
    """Run all Phase 1 tests"""
    print("="*70)
    print("🚀 PHASE 1 TESTING: Clean Architecture Refactor")
    print("="*70)
    
    tests = [
        test_imports,
        test_domain_models,
        test_session_service,
        test_backward_compatibility,
        test_dependency_injection
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        print(f"\n{test.__name__.replace('_', ' ').title()}")
        print("-" * 50)
        
        try:
            if test():
                passed += 1
                print("✅ PASSED")
            else:
                failed += 1
                print("❌ FAILED")
        except Exception as e:
            failed += 1
            print(f"❌ FAILED with exception: {e}")
    
    print("\n" + "="*70)
    print(f"📊 TEST RESULTS: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("✨ ALL TESTS PASSED! Phase 1 refactor is ready.")
        print("🚀 You can now use app.main_v2:app in your deployment.")
        print("📋 Follow the migration guide in PHASE1_MIGRATION.md")
    else:
        print("⚠️ Some tests failed. Please review before deploying.")
        print("🔄 You can still use the original app.main:app if needed.")
    
    print("="*70)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)