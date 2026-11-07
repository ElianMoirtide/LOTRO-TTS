import "Turbine";
import "Turbine.Gameplay";
import "Turbine.UI";
import "Turbine.UI.Lotro";

_G.TTS = _G.TTS or {};

local lang = Turbine.Engine.GetLanguage();
local label = "Vorlesen";
if lang == Turbine.Language.English then
    label = "Read aloud";
elseif lang == Turbine.Language.French then
    label = "Lire à haute voix";
end

-- Standard-Einstellungen
local defaults = {
    left = (Turbine.UI.Display:GetWidth() - 100) / 2,
    top = (Turbine.UI.Display:GetHeight() - 20) / 2,
    width = 100
};

-- Einstellungen laden (auf Charakter-Ebene)
local settings = nil;
pcall(function()
    settings = Turbine.PluginData.Load(Turbine.DataScope.Character, "TTS_WindowPos", function(data)
        if type(data) == "table" then
            settings = data;
        end
    end);
end);

if type(settings) ~= "table" then
    settings = {};
end
for k, v in pairs(defaults) do
    if settings[k] == nil then
        settings[k] = v;
    end
end

-- Funktion zum Speichern
local function SaveSettings()
    pcall(function()
        Turbine.PluginData.Save(Turbine.DataScope.Character, "TTS_WindowPos", settings, function() end);
    end);
end

-- Hauptfenster als Container
_G.TTS.window = Turbine.UI.Window();
_G.TTS.window:SetSize(settings.width, 20);
_G.TTS.window:SetPosition(settings.left, settings.top);
_G.TTS.window:SetVisible(true);

-- Echter LOTRO-Button
_G.TTS.button = Turbine.UI.Lotro.Button();
_G.TTS.button:SetParent(_G.TTS.window);
_G.TTS.button:SetSize(settings.width, 20);
_G.TTS.button:SetPosition(0, 0);
_G.TTS.button:SetText(label);
_G.TTS.button:SetVisible(false);

-- Hilfsfunktion: Aktualisiert Position und Breite
local function ApplySettings(left, top, width)
    settings.left = tonumber(left) or settings.left;
    settings.top = tonumber(top) or settings.top;
    settings.width = math.max(20, tonumber(width) or settings.width);

    _G.TTS.window:SetPosition(settings.left, settings.top);
    _G.TTS.window:SetSize(settings.width, 20);
    _G.TTS.button:SetSize(settings.width, 20);

    SaveSettings();
end

-- --- OPTIONS-PANEL FÜR DEN ZUSATZMODUL-MANAGER ---
local function CreateOptionsPanel()
    local optionsPanel = Turbine.UI.Control();
    optionsPanel:SetSize(400, 250);

    local function CreateSettingInput(parent, top, labelText, initialValue)
        local lbl = Turbine.UI.Label();
        lbl:SetParent(parent);
        lbl:SetPosition(20, top);
        lbl:SetSize(120, 20);
        lbl:SetText(labelText);
        lbl:SetTextAlignment(Turbine.UI.ContentAlignment.MiddleLeft);

        local txt = Turbine.UI.Lotro.TextBox();
        txt:SetParent(parent);
        txt:SetPosition(150, top);
        txt:SetSize(80, 22);
        txt:SetText(tostring(initialValue));
        txt:SetMultiline(false);

        return txt;
    end

    local txtLeft  = CreateSettingInput(optionsPanel, 20, "Position X (Links):", settings.left);
    local txtTop   = CreateSettingInput(optionsPanel, 50, "Position Y (Oben):", settings.top);
    local txtWidth = CreateSettingInput(optionsPanel, 80, "Breite:", settings.width);

    local btnSave = Turbine.UI.Lotro.Button();
    btnSave:SetParent(optionsPanel);
    btnSave:SetPosition(20, 120);
    btnSave:SetSize(120, 25);
    btnSave:SetText("Übernehmen");

    btnSave.Click = function()
        ApplySettings(txtLeft:GetText(), txtTop:GetText(), txtWidth:GetText());
    end

    optionsPanel.UpdateFields = function()
        txtLeft:SetText(tostring(settings.left));
        txtTop:SetText(tostring(settings.top));
        txtWidth:SetText(tostring(settings.width));
    end

    return optionsPanel;
end

local optionsControl = CreateOptionsPanel();
plugin.GetOptionsPanel = function(self)
    return optionsControl;
end;

-- --- STRG + DRAG & DROP LOGIK ---
local isDragging = false;
local dragStartX, dragStartY;

_G.TTS.button.MouseDown = function(sender, args)
    if args.Button == Turbine.UI.MouseButton.Left and Turbine.UI.Control.IsControlKeyDown() then
        isDragging = true;
        dragStartX = args.X;
        dragStartY = args.Y;
    end
end;

_G.TTS.button.MouseMove = function(sender, args)
    if isDragging then
        local screenX, screenY = Turbine.UI.Display.GetMousePosition();
        local newLeft = screenX - dragStartX;
        local newTop = screenY - dragStartY;
        _G.TTS.window:SetPosition(newLeft, newTop);
    end
end;

_G.TTS.button.MouseUp = function(sender, args)
    if args.Button == Turbine.UI.MouseButton.Left and isDragging then
        isDragging = false;
        local left, top = _G.TTS.window:GetPosition();
        ApplySettings(left, top, settings.width);
        optionsControl.UpdateFields();
    end
end;

_G.TTS.button.Click = function(sender, args)
    if isDragging then return end

    local player = Turbine.Gameplay.LocalPlayer.GetInstance();
    local name = "";
    if player ~= nil then
        local target = player:GetTarget();
        if target ~= nil then
            name = tostring(target:GetName());
        end
    end

    local code = "DE";
    if lang == Turbine.Language.English then
        code = "EN";
    elseif lang == Turbine.Language.French then
        code = "FR";
    end

    Turbine.Engine.ScriptLog("TTS|" .. code .. "|" .. name);
end;

-- --- ZIEL-ÜBERWACHUNG (EVENT-BASIERT STATT FRAME-POLLING) ---
-- player:GetTarget() erzeugt bei jedem Aufruf ein natives C++ Entity-Wrapper-Objekt.
-- Ein Abfragen pro Frame (Update-Event) erzeugt tausende Wrapper pro Minute im Speicher,
-- die der LOTRO-Client bei jedem Zielwechsel durchlaufen muss -> führt zu wachsenden Freezes.
-- Lösung: Ausschließlich ereignisbasiert auf TargetChanged reagieren.

local function AddCallback(object, event, callback)
    if object == nil then return nil end
    local existing = object[event];
    if existing == nil then
        object[event] = callback;
    elseif type(existing) == "table" then
        table.insert(existing, callback);
    elseif type(existing) == "function" then
        object[event] = { existing, callback };
    end
    return callback;
end

local function RemoveCallback(object, event, callback)
    if object == nil then return end
    local existing = object[event];
    if existing == callback then
        object[event] = nil;
    elseif type(existing) == "table" then
        for i, cb in ipairs(existing) do
            if cb == callback then
                table.remove(existing, i);
                break;
            end
        end
        if #existing == 1 then
            object[event] = existing[1];
        elseif #existing == 0 then
            object[event] = nil;
        end
    end
end

local localPlayer = nil;

local function RefreshButtonVisibility()
    local hasTarget = false;
    if localPlayer ~= nil then
        local target = localPlayer:GetTarget();
        hasTarget = (target ~= nil);
    end
    if _G.TTS.button:IsVisible() ~= hasTarget then
        _G.TTS.button:SetVisible(hasTarget);
    end
end

local function OnTargetChanged(sender, args)
    RefreshButtonVisibility();
end

-- Initialisierung: Wenn das Plugin beim Login automatisch geladen wird,
-- kann LocalPlayer.GetInstance() während des Ladebildschirms kurzzeitig nil sein.
local function SetupTargetListener()
    localPlayer = Turbine.Gameplay.LocalPlayer.GetInstance();
    if localPlayer ~= nil then
        AddCallback(localPlayer, "TargetChanged", OnTargetChanged);
        RefreshButtonVisibility();
        return true;
    end
    return false;
end

if not SetupTargetListener() then
    -- Falls beim Laden noch im Ladebildschirm: temporär Updates aktivieren,
    -- bis LocalPlayer existiert, danach sofort wieder komplett abschalten.
    _G.TTS.window:SetWantsUpdates(true);
    _G.TTS.window.Update = function(sender, args)
        if SetupTargetListener() then
            _G.TTS.window:SetWantsUpdates(false);
            _G.TTS.window.Update = nil;
        end
    end;
end

-- Beim Entladen des Plugins Listener sauber lösen und Fenster schließen
plugin.Unload = function(self)
    if localPlayer ~= nil then
        RemoveCallback(localPlayer, "TargetChanged", OnTargetChanged);
    end
    if _G.TTS.window ~= nil then
        _G.TTS.window:SetWantsUpdates(false);
        _G.TTS.window.Update = nil;
        _G.TTS.window:SetVisible(false);
    end
end;