/*
 * mod-llm-chatter - guild chatter hook ownership
 */

#include "LLMChatterGuild.h"
#include "LLMChatterConfig.h"
#include "LLMChatterShared.h"

#include "AchievementMgr.h"
#include "Chat.h"
#include "DatabaseEnv.h"
#include "Guild.h"
#include "Item.h"
#include "ItemTemplate.h"
#include "ObjectAccessor.h"
#include "Player.h"
#include "Playerbots.h"
#include "Random.h"
#include "RandomPlayerbotMgr.h"
#include "ScriptMgr.h"
#include "Timer.h"
#include "World.h"
#include "WorldSession.h"
#include "WorldSessionMgr.h"

#include <algorithm>
#include <string>
#include <vector>

namespace
{

std::string TrimGuildText(std::string text)
{
    size_t first = text.find_first_not_of(" \t\n\r");
    if (first == std::string::npos)
        return "";

    size_t last = text.find_last_not_of(" \t\n\r");
    return text.substr(first, last - first + 1);
}

std::string TruncateGuildText(
    std::string text, size_t maxLength)
{
    if (text.size() <= maxLength)
        return text;
    return text.substr(0, maxLength);
}

bool LooksLikeAddonOrColorOnly(std::string const& msg)
{
    bool hasUnderscore = false;
    bool allCapsOrSep = true;
    for (char c : msg)
    {
        if (c == '_')
            hasUnderscore = true;
        else if (c != ' ' && c != '\t'
            && c != '\n' && c != '\r'
            && !(c >= 'A' && c <= 'Z'))
        {
            allCapsOrSep = false;
            break;
        }
    }

    if (hasUnderscore && allCapsOrSep)
        return true;

    if (msg.size() <= 2 || msg[0] != '|'
        || msg[1] != 'c')
        return false;

    std::string stripped = msg;
    size_t start;
    size_t end;
    while ((start = stripped.find("|c"))
           != std::string::npos
        && (end = stripped.find("|r", start))
           != std::string::npos)
    {
        stripped.erase(start, end - start + 2);
    }

    stripped = TrimGuildText(stripped);
    return stripped.empty();
}

std::string GetCharacterNameByGuid(uint32 guid)
{
    if (!guid)
        return "";

    ObjectGuid objectGuid =
        ObjectGuid::Create<HighGuid::Player>(guid);
    if (Player* player =
            ObjectAccessor::FindConnectedPlayer(
                objectGuid))
    {
        return player->GetName();
    }

    QueryResult result = CharacterDatabase.Query(
        "SELECT name FROM characters "
        "WHERE guid = {} LIMIT 1",
        guid);

    if (!result)
        return "";

    Field* fields = result->Fetch();
    return fields[0].Get<std::string>();
}

bool HasOnlineRealGuildMember(
    Guild* guild, ObjectGuid excludeGuid = ObjectGuid::Empty)
{
    if (!guild)
        return false;

    WorldSessionMgr::SessionMap const& sessions =
        sWorldSessionMgr->GetAllSessions();
    for (auto const& pair : sessions)
    {
        WorldSession* session = pair.second;
        if (!session)
            continue;

        Player* member = session->GetPlayer();
        if (!member || !member->IsInWorld())
            continue;
        if (member->GetGuildId() != guild->GetId())
            continue;
        if (member->GetGUID() == excludeGuid)
            continue;
        if (IsPlayerBot(member))
            continue;

        return true;
    }

    return false;
}

bool HasOnlineGuildBot(
    Guild* guild, ObjectGuid excludeGuid = ObjectGuid::Empty)
{
    if (!guild)
        return false;

    auto allBots = sRandomPlayerbotMgr.GetAllBots();
    for (auto const& pair : allBots)
    {
        Player* bot = pair.second;
        if (!bot || !bot->IsInWorld())
            continue;
        if (bot->GetGuildId() != guild->GetId())
            continue;
        if (bot->GetGUID() == excludeGuid)
            continue;

        return true;
    }

    return false;
}

std::vector<Guild*> GetAmbientGuildCandidates()
{
    std::vector<Guild*> guilds;
    std::vector<uint32> seenGuildIds;

    WorldSessionMgr::SessionMap const& sessions =
        sWorldSessionMgr->GetAllSessions();
    for (auto const& pair : sessions)
    {
        WorldSession* session = pair.second;
        if (!session || session->PlayerLoading())
            continue;

        Player* player = session->GetPlayer();
        if (!player || !player->IsInWorld()
            || IsPlayerBot(player))
            continue;

        Guild* guild = player->GetGuild();
        if (!guild)
            continue;

        uint32 guildId = guild->GetId();
        if (std::find(
                seenGuildIds.begin(),
                seenGuildIds.end(),
                guildId)
            != seenGuildIds.end())
        {
            continue;
        }

        if (!HasOnlineGuildBot(guild))
            continue;

        seenGuildIds.push_back(guildId);
        guilds.push_back(guild);
    }

    return guilds;
}

uint8 GetGuildRankId(Guild* guild, Player* player, uint8 fallback)
{
    if (!guild || !player)
        return fallback;

    Guild::Member const* member =
        guild->GetMember(player->GetGUID());
    if (!member)
        return fallback;

    return member->GetRankId();
}

std::string GetGuildRankName(Guild* guild, uint8 rankId)
{
    if (!guild)
        return "";

    // Guild::GetRankInfo()/RankInfo are private to the core,
    // so resolve the rank name from the guild_rank table.
    QueryResult result = CharacterDatabase.Query(
        "SELECT rname FROM guild_rank "
        "WHERE guildid = {} AND rid = {} LIMIT 1",
        guild->GetId(), rankId);

    if (!result)
        return "";

    Field* fields = result->Fetch();
    return fields[0].Get<std::string>();
}

bool IsGuildEventOnCooldown(
    std::string const& cooldownKey,
    uint32 cooldownSeconds)
{
    if (cooldownKey.empty() || cooldownSeconds == 0)
        return false;

    QueryResult result = CharacterDatabase.Query(
        "SELECT 1 FROM llm_chatter_events "
        "WHERE cooldown_key = '{}' "
        "AND created_at > "
        "DATE_SUB(NOW(), INTERVAL {} SECOND) "
        "LIMIT 1",
        EscapeString(cooldownKey),
        cooldownSeconds);

    return static_cast<bool>(result);
}

std::string BuildGuildJson(Guild* guild)
{
    if (!guild)
        return "\"guild_id\":0,"
               "\"guild_name\":\"\","
               "\"guild_motd\":\"\","
               "\"guild_info\":\"\"";

    return "\"guild_id\":" +
        std::to_string(guild->GetId()) +
        ",\"guild_name\":\"" +
        JsonEscape(guild->GetName()) +
        "\",\"guild_motd\":\"" +
        JsonEscape(
            TruncateGuildText(
                guild->GetMOTD(), 220)) +
        "\",\"guild_info\":\"" +
        JsonEscape(
            TruncateGuildText(
                guild->GetInfo(), 220)) +
        "\"";
}

std::string BuildPlayerJson(
    Player* player, char const* prefix)
{
    std::string key(prefix);
    if (!player)
    {
        return "\"" + key + "_guid\":0,"
            "\"" + key + "_name\":\"\","
            "\"" + key + "_class\":0,"
            "\"" + key + "_race\":0,"
            "\"" + key + "_gender\":0,"
            "\"" + key + "_level\":0,"
            "\"" + key + "_zone_id\":0,"
            "\"" + key + "_area_id\":0,"
            "\"" + key + "_map_id\":0,"
            "\"" + key + "_zone_name\":\"\","
            "\"" + key + "_class_name\":\"\","
            "\"" + key + "_race_name\":\"\"";
    }

    uint32 zoneId = player->GetZoneId();
    return "\"" + key + "_guid\":" +
        std::to_string(player->GetGUID().GetCounter()) +
        ",\"" + key + "_name\":\"" +
        JsonEscape(player->GetName()) +
        "\",\"" + key + "_class\":" +
        std::to_string(player->getClass()) +
        ",\"" + key + "_race\":" +
        std::to_string(player->getRace()) +
        ",\"" + key + "_gender\":" +
        std::to_string(player->getGender()) +
        ",\"" + key + "_level\":" +
        std::to_string(player->GetLevel()) +
        ",\"" + key + "_zone_id\":" +
        std::to_string(zoneId) +
        ",\"" + key + "_area_id\":" +
        std::to_string(player->GetAreaId()) +
        ",\"" + key + "_map_id\":" +
        std::to_string(player->GetMapId()) +
        ",\"" + key + "_zone_name\":\"" +
        JsonEscape(GetZoneName(zoneId)) +
        "\",\"" + key + "_class_name\":\"" +
        JsonEscape(GetChatterClassName(
            player->getClass())) +
        "\",\"" + key + "_race_name\":\"" +
        JsonEscape(GetRaceName(player->getRace())) +
        "\"";
}

std::string BuildPlayerRankJson(
    Guild* guild, Player* player,
    char const* prefix, uint8 fallbackRank)
{
    std::string key(prefix);
    uint8 rankId = GetGuildRankId(
        guild, player, fallbackRank);

    return "\"" + key + "_rank_id\":" +
        std::to_string(rankId) +
        ",\"" + key + "_rank_name\":\"" +
        JsonEscape(GetGuildRankName(guild, rankId)) +
        "\"";
}

std::string BuildGuidNameJson(
    uint32 guid, char const* prefix)
{
    std::string key(prefix);
    return "\"" + key + "_guid\":" +
        std::to_string(guid) +
        ",\"" + key + "_name\":\"" +
        JsonEscape(GetCharacterNameByGuid(guid)) +
        "\"";
}

void QueueGuildEvent(
    char const* eventType, Guild* guild,
    std::string const& cooldownKey,
    uint32 cooldownSeconds,
    uint32 subjectGuid,
    std::string const& subjectName,
    uint32 targetGuid,
    std::string const& targetName,
    std::string const& extraData,
    uint32 expiresAfterSeconds = 180)
{
    if (!guild || IsGuildEventOnCooldown(
            cooldownKey, cooldownSeconds))
        return;

    QueueChatterEvent(
        eventType,
        "global",
        0,
        0,
        GetChatterEventPriority(eventType),
        cooldownKey,
        subjectGuid,
        subjectName,
        targetGuid,
        targetName,
        0,
        EscapeString(extraData),
        GetReactionDelaySeconds(eventType),
        expiresAfterSeconds,
        true);
}

bool CanQueueGuildSocialEvent(
    Guild* guild, std::string const& eventKind,
    uint32 cooldownSeconds)
{
    if (!sLLMChatterConfig
        || !sLLMChatterConfig->IsEnabled()
        || !sLLMChatterConfig->_guildChatEnable
        || !guild)
    {
        return false;
    }

    if (!HasOnlineGuildBot(guild)
        || !HasOnlineRealGuildMember(guild))
        return false;

    if (urand(1, 100)
        > sLLMChatterConfig->_guildChatEventChance)
        return false;

    std::string cooldownKey =
        "guild_event:" +
        std::to_string(guild->GetId()) + ":" +
        eventKind;
    return !IsGuildEventOnCooldown(
        cooldownKey, cooldownSeconds);
}

void QueueGuildSocialEvent(
    Guild* guild, std::string const& eventKind,
    std::string const& extraFields,
    uint32 subjectGuid = 0,
    std::string const& subjectName = "",
    uint32 targetGuid = 0,
    std::string const& targetName = "",
    uint32 cooldownSeconds = 0)
{
    if (!sLLMChatterConfig)
        return;

    uint32 cooldown =
        cooldownSeconds
            ? cooldownSeconds
            : sLLMChatterConfig->_guildChatEventCooldown;
    if (!CanQueueGuildSocialEvent(
            guild, eventKind, cooldown))
    {
        return;
    }

    std::string extraData = "{"
        + BuildGuildJson(guild) +
        ",\"event_kind\":\"" +
        JsonEscape(eventKind) + "\"";
    if (!extraFields.empty())
        extraData += "," + extraFields;
    extraData += "}";

    QueueGuildEvent(
        "guild_social_event",
        guild,
        "guild_event:" +
            std::to_string(guild->GetId()) + ":" +
            eventKind,
        cooldown,
        subjectGuid,
        subjectName,
        targetGuid,
        targetName,
        extraData);
}

class LLMChatterGuildWorldScript : public WorldScript
{
public:
    LLMChatterGuildWorldScript()
        : WorldScript(
              "LLMChatterGuildWorldScript",
              {WORLDHOOK_ON_UPDATE}) {}

    void OnUpdate(uint32 /*diff*/) override
    {
        if (!sLLMChatterConfig
            || !sLLMChatterConfig->IsEnabled()
            || !sLLMChatterConfig->_guildChatEnable
            || !sLLMChatterConfig->_guildChatAmbientEnable)
        {
            return;
        }

        uint32 intervalSeconds = std::max<uint32>(
            10,
            sLLMChatterConfig
                ->_guildChatAmbientIntervalSeconds);
        uint32 now = getMSTime();
        if (now - _lastGuildAmbientTime
            < intervalSeconds * 1000)
        {
            return;
        }

        _lastGuildAmbientTime = now;
        if (urand(1, 100)
            > sLLMChatterConfig->_guildChatAmbientChance)
        {
            return;
        }

        std::vector<Guild*> guilds =
            GetAmbientGuildCandidates();
        if (guilds.empty())
            return;

        uint32 index = urand(
            0,
            static_cast<uint32>(guilds.size() - 1));
        Guild* guild = guilds[index];
        if (!guild)
            return;

        std::string extraData = "{"
            + BuildGuildJson(guild) +
            ",\"event_kind\":\"ambient\","
            "\"ambient_reason\":\"periodic\"}";
        std::string cooldownKey =
            "guild_ambient:" +
            std::to_string(guild->GetId());

        QueueGuildEvent(
            "guild_ambient",
            guild,
            cooldownKey,
            sLLMChatterConfig->_guildChatAmbientCooldown,
            0,
            "",
            0,
            "",
            extraData,
            180);
    }

private:
    uint32 _lastGuildAmbientTime = 0;
};

class LLMChatterGuildPlayerScript : public PlayerScript
{
public:
    LLMChatterGuildPlayerScript()
        : PlayerScript(
              "LLMChatterGuildPlayerScript",
              {PLAYERHOOK_CAN_PLAYER_USE_GUILD_CHAT,
               PLAYERHOOK_ON_LOGIN,
               PLAYERHOOK_ON_LEVEL_CHANGED,
               PLAYERHOOK_ON_ACHI_COMPLETE}) {}

    bool OnPlayerCanUseChat(
        Player* player, uint32 type, uint32 language,
        std::string& msg, Guild* guild) override
    {
        if (!sLLMChatterConfig
            || !sLLMChatterConfig->IsEnabled()
            || !sLLMChatterConfig->_guildChatEnable)
            return true;

        if (!player || !guild
            || type != CHAT_MSG_GUILD
            || language == LANG_ADDON
            || IsPlayerBot(player))
            return true;

        std::string safeMsg = TrimGuildText(msg);
        if (safeMsg.empty()
            || LooksLikeAddonOrColorOnly(safeMsg))
            return true;

        if (safeMsg.size()
            > sLLMChatterConfig->_maxMessageLength)
        {
            safeMsg = safeMsg.substr(
                0,
                sLLMChatterConfig
                    ->_maxMessageLength);
        }

        if (!HasOnlineGuildBot(guild, player->GetGUID()))
            return true;

        if (urand(1, 100)
            > sLLMChatterConfig
                ->_guildChatPlayerMessageChance)
            return true;

        std::string cooldownKey =
            "guild_player_msg:" +
            std::to_string(guild->GetId());
        if (IsGuildEventOnCooldown(
                cooldownKey,
                sLLMChatterConfig
                    ->_guildChatPlayerMessageCooldown))
            return true;

        uint8 rankId = GetGuildRankId(guild, player, 0);
        std::string extraData = "{"
            + BuildGuildJson(guild) + ","
            + BuildPlayerJson(player, "player") + ","
            + BuildPlayerRankJson(
                guild, player, "player", rankId) +
            ",\"player_message\":\"" +
            JsonEscape(safeMsg) + "\"}";

        QueueGuildEvent(
            "guild_player_msg",
            guild,
            cooldownKey,
            sLLMChatterConfig
                ->_guildChatPlayerMessageCooldown,
            player->GetGUID().GetCounter(),
            player->GetName(),
            0,
            "",
            extraData,
            120);

        return true;
    }

    void OnPlayerLogin(Player* player) override
    {
        if (!sLLMChatterConfig
            || !sLLMChatterConfig->IsEnabled()
            || !sLLMChatterConfig->_guildChatEnable)
            return;

        if (!player)
            return;

        Guild* guild = player->GetGuild();
        if (!guild)
            return;

        if (!IsPlayerBot(player))
        {
            if (!sLLMChatterConfig
                    ->_guildChatPlayerLoginGreetingEnable)
                return;

            if (!HasOnlineGuildBot(guild, player->GetGUID()))
                return;

            if (urand(1, 100)
                > sLLMChatterConfig
                    ->_guildChatPlayerLoginGreetingChance)
                return;

            std::string cooldownKey =
                "guild_player_login:" +
                std::to_string(guild->GetId()) + ":" +
                std::to_string(
                    player->GetGUID().GetCounter());
            if (IsGuildEventOnCooldown(
                    cooldownKey,
                    sLLMChatterConfig
                        ->_guildChatPlayerLoginGreetingCooldown))
                return;

            uint8 rankId = GetGuildRankId(guild, player, 0);
            std::string extraData = "{"
                + BuildGuildJson(guild) + "," +
                "\"event_kind\":\"member_online\","
                + BuildPlayerJson(player, "player") + "," +
                BuildPlayerRankJson(
                    guild, player, "player", rankId) +
                "}";

            QueueGuildEvent(
                "guild_social_event",
                guild,
                cooldownKey,
                sLLMChatterConfig
                    ->_guildChatPlayerLoginGreetingCooldown,
                player->GetGUID().GetCounter(),
                player->GetName(),
                0,
                "",
                extraData,
                180);
            return;
        }

        if (!sLLMChatterConfig
                ->_guildChatLoginGreetingEnable)
            return;

        if (!HasOnlineRealGuildMember(
                guild, player->GetGUID()))
            return;

        std::string joinKey =
            "guild_join:" +
            std::to_string(guild->GetId()) + ":" +
            std::to_string(
                player->GetGUID().GetCounter());
        if (IsGuildEventOnCooldown(joinKey, 45))
            return;

        std::string cooldownKey =
            "guild_login:" +
            std::to_string(guild->GetId()) + ":" +
            std::to_string(
                player->GetGUID().GetCounter());

        if (IsGuildEventOnCooldown(cooldownKey, 120))
            return;

        bool motdFocus =
            urand(1, 100)
            <= sLLMChatterConfig
                ->_guildChatMotdLoginChance;
        uint8 rankId = GetGuildRankId(guild, player, 0);

        std::string extraData = "{"
            + BuildGuildJson(guild) + ","
            + BuildPlayerJson(player, "bot") + ","
            + BuildPlayerRankJson(
                guild, player, "bot", rankId) +
            ",\"motd_focus\":" +
            std::string(motdFocus ? "true" : "false") +
            "}";

        QueueGuildEvent(
            "guild_bot_login",
            guild,
            cooldownKey,
            120,
            player->GetGUID().GetCounter(),
            player->GetName(),
            0,
            "",
            extraData,
            120);
    }

    void OnPlayerLevelChanged(
        Player* player, uint8 oldLevel) override
    {
        if (!sLLMChatterConfig
            || !sLLMChatterConfig->IsEnabled()
            || !sLLMChatterConfig->_guildChatEnable
            || !sLLMChatterConfig
                    ->_guildChatLevelAchievementEchoEnable)
            return;

        if (!player || !IsPlayerBot(player))
            return;

        Guild* guild = player->GetGuild();
        if (!guild
            || !HasOnlineRealGuildMember(
                guild, player->GetGUID()))
            return;

        uint8 rankId = GetGuildRankId(guild, player, 0);
        std::string extraFields =
            BuildPlayerJson(player, "bot") + "," +
            BuildPlayerRankJson(
                guild, player, "bot", rankId) +
            ",\"old_level\":" +
            std::to_string(oldLevel) +
            ",\"new_level\":" +
            std::to_string(player->GetLevel());

        QueueGuildSocialEvent(
            guild,
            "bot_level_up",
            extraFields,
            player->GetGUID().GetCounter(),
            player->GetName(),
            0,
            "",
            sLLMChatterConfig
                ->_guildChatLevelAchievementEchoCooldown);
    }

    void OnPlayerAchievementComplete(
        Player* player,
        AchievementEntry const* achievement) override
    {
        if (!sLLMChatterConfig
            || !sLLMChatterConfig->IsEnabled()
            || !sLLMChatterConfig->_guildChatEnable
            || !sLLMChatterConfig
                    ->_guildChatLevelAchievementEchoEnable)
            return;

        if (!player || !achievement
            || !IsPlayerBot(player))
            return;

        Guild* guild = player->GetGuild();
        if (!guild
            || !HasOnlineRealGuildMember(
                guild, player->GetGUID()))
            return;

        std::string achievementName =
            achievement->name[0]
                ? achievement->name[0] : "";
        uint8 rankId = GetGuildRankId(guild, player, 0);
        std::string extraFields =
            BuildPlayerJson(player, "bot") + "," +
            BuildPlayerRankJson(
                guild, player, "bot", rankId) +
            ",\"achievement_id\":" +
            std::to_string(achievement->ID) +
            ",\"achievement_name\":\"" +
            JsonEscape(achievementName) + "\"";

        QueueGuildSocialEvent(
            guild,
            "bot_achievement",
            extraFields,
            player->GetGUID().GetCounter(),
            player->GetName(),
            0,
            "",
            sLLMChatterConfig
                ->_guildChatLevelAchievementEchoCooldown);
    }
};

class LLMChatterGuildScript : public GuildScript
{
public:
    LLMChatterGuildScript()
        : GuildScript(
              "LLMChatterGuildScript",
              {GUILDHOOK_ON_ADD_MEMBER,
               GUILDHOOK_ON_MOTD_CHANGED,
               GUILDHOOK_ON_INFO_CHANGED,
               GUILDHOOK_ON_MEMBER_WITDRAW_MONEY,
               GUILDHOOK_ON_MEMBER_DEPOSIT_MONEY,
               GUILDHOOK_ON_ITEM_MOVE,
               GUILDHOOK_ON_EVENT,
               GUILDHOOK_ON_BANK_EVENT}) {}

    void OnAddMember(
        Guild* guild, Player* player,
        uint8& plRank) override
    {
        if (!sLLMChatterConfig
            || !sLLMChatterConfig->IsEnabled()
            || !sLLMChatterConfig->_guildChatEnable
            || !sLLMChatterConfig
                    ->_guildChatJoinGreetingEnable)
            return;

        if (!guild || !player
            || !IsPlayerBot(player))
            return;

        if (!HasOnlineRealGuildMember(
                guild, player->GetGUID()))
            return;

        std::string cooldownKey =
            "guild_join:" +
            std::to_string(guild->GetId()) + ":" +
            std::to_string(
                player->GetGUID().GetCounter());

        uint8 rankId = GetGuildRankId(
            guild, player, plRank);
        std::string extraData = "{"
            + BuildGuildJson(guild) + ","
            + BuildPlayerJson(player, "bot") + ","
            + BuildPlayerRankJson(
                guild, player, "bot", rankId) +
            ",\"welcome_reply_min\":" +
            std::to_string(
                sLLMChatterConfig
                    ->_guildChatWelcomeReplyMin) +
            ",\"welcome_reply_max\":" +
            std::to_string(
                sLLMChatterConfig
                    ->_guildChatWelcomeReplyMax) +
            "}";

        QueueGuildEvent(
            "guild_member_joined",
            guild,
            cooldownKey,
            120,
            player->GetGUID().GetCounter(),
            player->GetName(),
            0,
            "",
            extraData,
            180);
    }

    void OnMOTDChanged(
        Guild* guild,
        const std::string& newMotd) override
    {
        std::string extraFields =
            "\"new_motd\":\"" +
            JsonEscape(
                TruncateGuildText(newMotd, 220)) +
            "\"";
        QueueGuildSocialEvent(
            guild, "motd_changed", extraFields);
    }

    void OnInfoChanged(
        Guild* guild,
        const std::string& newInfo) override
    {
        std::string extraFields =
            "\"new_info\":\"" +
            JsonEscape(
                TruncateGuildText(newInfo, 220)) +
            "\"";
        QueueGuildSocialEvent(
            guild, "info_changed", extraFields);
    }

    void OnMemberWitdrawMoney(
        Guild* guild, Player* player,
        uint32& amount, bool isRepair) override
    {
        if (!player)
            return;

        uint8 rankId = GetGuildRankId(guild, player, 0);
        std::string extraFields =
            BuildPlayerJson(player, "player") + "," +
            BuildPlayerRankJson(
                guild, player, "player", rankId) +
            ",\"amount\":" +
            std::to_string(amount) +
            ",\"is_repair\":" +
            std::string(isRepair ? "true" : "false");

        QueueGuildSocialEvent(
            guild,
            isRepair
                ? "bank_repair_money"
                : "bank_withdraw_money",
            extraFields,
            player->GetGUID().GetCounter(),
            player->GetName());
    }

    void OnMemberDepositMoney(
        Guild* guild, Player* player,
        uint32& amount) override
    {
        if (!player)
            return;

        uint8 rankId = GetGuildRankId(guild, player, 0);
        std::string extraFields =
            BuildPlayerJson(player, "player") + "," +
            BuildPlayerRankJson(
                guild, player, "player", rankId) +
            ",\"amount\":" +
            std::to_string(amount);

        QueueGuildSocialEvent(
            guild,
            "bank_deposit_money",
            extraFields,
            player->GetGUID().GetCounter(),
            player->GetName());
    }

    void OnItemMove(
        Guild* guild, Player* player, Item* pItem,
        bool isSrcBank, uint8 srcContainer,
        uint8 srcSlotId, bool isDestBank,
        uint8 destContainer,
        uint8 destSlotId) override
    {
        if (!player || !pItem)
            return;

        char const* eventKind = "bank_move_item";
        if (!isSrcBank && isDestBank)
            eventKind = "bank_deposit_item";
        else if (isSrcBank && !isDestBank)
            eventKind = "bank_withdraw_item";

        ItemTemplate const* itemTemplate =
            pItem->GetTemplate();
        std::string itemName =
            itemTemplate ? itemTemplate->Name1 : "";

        uint8 rankId = GetGuildRankId(guild, player, 0);
        std::string extraFields =
            BuildPlayerJson(player, "player") + "," +
            BuildPlayerRankJson(
                guild, player, "player", rankId) +
            ",\"item_entry\":" +
            std::to_string(pItem->GetEntry()) +
            ",\"item_name\":\"" +
            JsonEscape(itemName) +
            "\",\"source_is_bank\":" +
            std::string(isSrcBank ? "true" : "false") +
            ",\"dest_is_bank\":" +
            std::string(isDestBank ? "true" : "false") +
            ",\"source_container\":" +
            std::to_string(srcContainer) +
            ",\"source_slot\":" +
            std::to_string(srcSlotId) +
            ",\"dest_container\":" +
            std::to_string(destContainer) +
            ",\"dest_slot\":" +
            std::to_string(destSlotId);

        QueueGuildSocialEvent(
            guild,
            eventKind,
            extraFields,
            player->GetGUID().GetCounter(),
            player->GetName());
    }

    void OnEvent(
        Guild* guild, uint8 eventType,
        ObjectGuid::LowType playerGuid1,
        ObjectGuid::LowType playerGuid2,
        uint8 newRank) override
    {
        if (!guild)
            return;

        std::string eventKind;
        switch (eventType)
        {
            case GUILD_EVENT_LOG_INVITE_PLAYER:
                eventKind = "member_invited";
                break;
            case GUILD_EVENT_LOG_JOIN_GUILD:
                return;
            case GUILD_EVENT_LOG_PROMOTE_PLAYER:
                eventKind = "member_promoted";
                break;
            case GUILD_EVENT_LOG_DEMOTE_PLAYER:
                eventKind = "member_demoted";
                break;
            case GUILD_EVENT_LOG_UNINVITE_PLAYER:
                eventKind = "member_removed";
                break;
            case GUILD_EVENT_LOG_LEAVE_GUILD:
                eventKind = "member_left";
                break;
            default:
                eventKind = "guild_event";
                break;
        }

        std::string subjectName =
            GetCharacterNameByGuid(playerGuid1);
        std::string targetName =
            GetCharacterNameByGuid(playerGuid2);

        std::string extraFields =
            BuildGuidNameJson(playerGuid1, "actor") +
            "," +
            BuildGuidNameJson(playerGuid2, "target") +
            ",\"guild_event_type\":" +
            std::to_string(eventType) +
            ",\"new_rank_id\":" +
            std::to_string(newRank) +
            ",\"new_rank_name\":\"" +
            JsonEscape(
                GetGuildRankName(guild, newRank)) +
            "\"";

        QueueGuildSocialEvent(
            guild,
            eventKind,
            extraFields,
            playerGuid1,
            subjectName,
            playerGuid2,
            targetName);
    }

    void OnBankEvent(
        Guild* guild, uint8 eventType,
        uint8 /*tabId*/,
        ObjectGuid::LowType playerGuid,
        uint32 /*itemOrMoney*/,
        uint16 /*itemStackCount*/,
        uint8 /*destTabId*/) override
    {
        if (eventType != GUILD_BANK_LOG_BUY_SLOT)
            return;

        std::string playerName =
            GetCharacterNameByGuid(playerGuid);
        std::string extraFields =
            BuildGuidNameJson(playerGuid, "player") +
            ",\"guild_bank_event_type\":" +
            std::to_string(eventType);

        QueueGuildSocialEvent(
            guild,
            "bank_tab_purchased",
            extraFields,
            playerGuid,
            playerName);
    }
};

} // namespace

void AddLLMChatterGuildScripts()
{
    new LLMChatterGuildWorldScript();
    new LLMChatterGuildPlayerScript();
    new LLMChatterGuildScript();
}
