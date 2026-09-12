from database.core import (init_db, get_connection, reset_database_for_new_season,
    backup_database_vacuum, get_db_file_stats, get_league_stats, sync_persistent_backup, _lock)
from database.clubs import add_club, get_club, get_all_clubs, update_club_full, rebrand_club
from database.players import (add_or_update_player, get_player, get_player_by_discord_id,
    is_player_under_contract, terminate_player_contract, extend_player_contract,
    get_all_players, get_club_player_count, get_club_players, delete_player,
    set_player_warning_flag)
from database.applications import (create_application, get_application, get_pending_applications,
    get_stale_pending_applications, set_application_message, set_application_agreement,
    set_application_status, try_claim_application_for_approval, revert_application_status,
    reset_stuck_processing_applications, restore_application)
from database.free_agents import (register_free_agent, remove_free_agent, get_free_agents_paginated,
    get_all_free_agents, is_free_agent, cleanup_expired_free_agents)
from database.history import add_transfer_history, get_player_transfer_history
from database.settings import (get_setting, set_setting, delete_setting, get_next_ticket_id,
    is_market_open, set_market_status, get_market_state)

__all__ = [
    'init_db', 'get_connection', 'reset_database_for_new_season', 'backup_database_vacuum',
    'get_db_file_stats', 'get_league_stats', 'sync_persistent_backup', '_lock',
    'add_club', 'get_club', 'get_all_clubs', 'update_club_full', 'rebrand_club',
    'add_or_update_player', 'get_player', 'get_player_by_discord_id',
    'is_player_under_contract', 'terminate_player_contract', 'extend_player_contract',
    'get_all_players', 'get_club_player_count', 'get_club_players', 'delete_player',
    'set_player_warning_flag',
    'create_application', 'get_application', 'get_pending_applications',
    'get_stale_pending_applications', 'set_application_message', 'set_application_agreement',
    'set_application_status', 'try_claim_application_for_approval', 'revert_application_status',
    'reset_stuck_processing_applications', 'restore_application',
    'register_free_agent', 'remove_free_agent', 'get_free_agents_paginated',
    'get_all_free_agents', 'is_free_agent', 'cleanup_expired_free_agents',
    'add_transfer_history', 'get_player_transfer_history',
    'get_setting', 'set_setting', 'delete_setting', 'get_next_ticket_id',
    'is_market_open', 'set_market_status', 'get_market_state',
]
