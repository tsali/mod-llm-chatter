-- Add guild chatter event types and per-guild chat history.
-- Idempotent: guarded by COLUMN_TYPE check and CREATE TABLE IF NOT EXISTS.

SET @has_guild_chat = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME   = 'llm_chatter_events'
    AND COLUMN_NAME  = 'event_type'
    AND COLUMN_TYPE LIKE '%guild_player_msg%'
);

SET @sql = IF(@has_guild_chat = 0,
  "ALTER TABLE `llm_chatter_events`
  MODIFY COLUMN `event_type` ENUM(
    'weather_change',
    'holiday_start',
    'holiday_end',
    'creature_death_boss',
    'creature_death_rare',
    'creature_death_guard',
    'player_enters_zone',
    'bot_pvp_kill',
    'bot_level_up',
    'bot_achievement',
    'bot_quest_complete',
    'world_boss_spawn',
    'rare_spawn',
    'transport_arrives',
    'day_night_transition',
    'enemy_player_near',
    'bot_loot_item',
    'bot_group_join',
    'bot_group_kill',
    'bot_group_death',
    'bot_group_loot',
    'bot_group_player_msg',
    'bot_group_general_reaction',
    'bot_group_combat',
    'bot_group_levelup',
    'bot_group_quest_complete',
    'bot_group_achievement',
    'bot_group_spell_cast',
    'bot_group_quest_objectives',
    'bot_group_resurrect',
    'bot_group_zone_transition',
    'bot_group_dungeon_entry',
    'bot_group_wipe',
    'bot_group_corpse_run',
    'player_general_msg',
    'minor_event',
    'bot_group_low_health',
    'bot_group_oom',
    'bot_group_aggro_loss',
    'bot_group_quest_accept',
    'bot_group_quest_accept_batch',
    'weather_ambient',
    'bot_group_nearby_object',
    'bot_group_join_batch',
    'bg_match_start',
    'bg_match_end',
    'bg_pvp_kill',
    'bg_flag_picked_up',
    'bg_flag_dropped',
    'bg_flag_captured',
    'bg_flag_returned',
    'bg_node_contested',
    'bg_node_captured',
    'bg_score_milestone',
    'bg_idle_chatter',
    'bg_player_arrival',
    'raid_boss_pull',
    'raid_boss_kill',
    'raid_boss_wipe',
    'raid_idle_morale',
    'bot_group_farewell',
    'bot_group_subzone_change',
    'bot_group_emote_observer',
    'bot_group_emote_reaction',
    'bot_group_screenshot_observation',
    'proximity_say',
    'proximity_conversation',
    'proximity_reply',
    'proximity_player_say',
    'proximity_player_conversation',
    'guild_player_msg',
    'guild_member_joined',
    'guild_bot_login',
    'guild_social_event',
    'guild_ambient',
    'bot_backstory_regen',
    'bot_tone_regen'
  ) NOT NULL",
  "SELECT 1"
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS `llm_guild_chat_history` (
  `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  `guild_id` INT UNSIGNED NOT NULL,
  `speaker_guid` INT UNSIGNED DEFAULT NULL,
  `speaker_name` VARCHAR(64) NOT NULL,
  `is_bot` TINYINT(1) NOT NULL DEFAULT 0,
  `message` VARCHAR(255) NOT NULL,
  `event_type` VARCHAR(48) DEFAULT NULL,
  `topic_category` VARCHAR(64) DEFAULT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX `idx_guild_id` (`guild_id`),
  INDEX `idx_created_at` (`created_at`),
  INDEX `idx_guild_created` (`guild_id`, `created_at`),
  INDEX `idx_guild_topic` (`guild_id`, `topic_category`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `llm_guild_chat_pacing` (
  `guild_id` INT UNSIGNED NOT NULL,
  `next_available_at` TIMESTAMP NULL DEFAULT NULL,
  `last_activity_at` TIMESTAMP NULL DEFAULT NULL,
  `last_policy` VARCHAR(24) DEFAULT NULL,
  `last_reason` VARCHAR(64) DEFAULT NULL,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
      ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`guild_id`),
  KEY `idx_updated_at` (`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
