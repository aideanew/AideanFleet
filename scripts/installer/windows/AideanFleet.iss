; AideanFleet Windows 安装器（TASK-201，ADR-003）
; 工具：Inno Setup 6（iscc）。构建：iscc scripts\installer\windows\AideanFleet.iss
; 前置：先运行 python scripts\installer\windows\fetch_runtimes.py（运行时产物就绪），
;       python -m build --wheel 与前端构建完成，wheelhouse 就绪。
; 原则（MN-03）：按用户安装（PrivilegesRequired=lowest），不写 HKLM，不改系统 PATH。

#define MyAppName "AideanFleet"
#define MyAppVersion "0.4.0"
#define MyAppExeName "AideanFleet"
#define RuntimeDir "_runtimes"
#define DistDir "..\..\..\fleet\console\dist"
#define WheelhouseDir "_wheelhouse"

[Setup]
AppId={{7E1A2C64-5B7E-4B5A-9C1D-AIDEANFLEET01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=AideanFleet
DefaultDirName={localappdata}\Programs\AideanFleet
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\..\..\dist-installer
OutputBaseFilename=AideanFleet-Setup-{#MyAppVersion}-UNSIGNED
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\runtime\python\python.exe

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
; 私有运行时（离线内置，A-14）
Source: "{#RuntimeDir}\python-3.11.9-embed-amd64.zip"; DestDir: "{app}\_packages"; Flags: ignoreversion
Source: "{#RuntimeDir}\node-v22.20.0-win-x64.zip"; DestDir: "{app}\_packages"; Flags: ignoreversion
; 前端 dist（随 wheel）
Source: "{#DistDir}\*"; DestDir: "{app}\fleet\console\dist"; Flags: ignoreversion recursesubdirs
; wheelhouse（AideanFleet wheel + 依赖 wheel，pip --no-index 安装）
Source: "{#WheelhouseDir}\*.whl"; DestDir: "{app}\wheelhouse"; Flags: ignoreversion
; 启动器（修复 N3：快捷方式/安装后自启引用 {app}\launcher.cmd，但 [Files] 从未拷贝 → 必然失效）
Source: "launcher.cmd"; DestDir: "{app}"; Flags: ignoreversion
; 配置模板（修复 N4：wheel 装进 site-packages 后 paths().root 下无 .env.example → ensure_env_file() 抛 ConfigError；
; 配合 launcher.cmd 注入 FLEET_ROOT={app}，模板随装到 {app}\.env.example，首启即可复制出 .env）
Source: "..\..\..\.env.example"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\runtime\python"
Name: "{app}\runtime\node"
Name: "{app}\npm-global"
Name: "{userappdata}\AideanFleet\data"; Permissions: users-modify

[Code]
var
  DataPage: TInputOptionWizardPage;

// arm64 检测（TASK-201 步骤 6）：不支持即 UNSUPPORTED_ARCH 退出
function InitializeSetup(): Boolean;
var
  IsArm64: Boolean;
begin
  IsArm64 := (ProcessorArchitecture = paARM64) or (ProcessorArchitecture = paARM32);
  if IsArm64 then
  begin
    MsgBox('UNSUPPORTED_ARCH：AideanFleet 当前仅提供 x64 Windows 安装包。', mbError, MB_OK);
    Result := False;
  end
  else
    Result := True;
end;

// 解压私有运行时（构建期内置 zip → runtime\python 与 runtime\node）
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  PythonZip, NodeZip, PythonDir, NodeDir: String;
begin
  if CurStep = ssInstall then
  begin
    PythonZip := ExpandConstant('{app}\_packages\python-3.11.9-embed-amd64.zip');
    NodeZip := ExpandConstant('{app}\_packages\node-v22.20.0-win-x64.zip');
    PythonDir := ExpandConstant('{app}\runtime\python');
    NodeDir := ExpandConstant('{app}\runtime\node');
    // 修复 N2：Exec 曾捕获 ResultCode 却从不判定——失败时安装器仍报“成功”，用户点快捷方式才炸
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Format('-NoProfile -Command "Expand-Archive -Force ''%s'' ''%s''"', [PythonZip, PythonDir]),
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
    begin
      MsgBox('Python 运行时解压失败（退出码 ' + IntToStr(ResultCode) + '）。请重新运行安装器；若持续失败请联系支持。', mbError, MB_OK);
      RaiseException('RUNTIME_EXTRACT_FAILED');
    end;
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Format('-NoProfile -Command "Expand-Archive -Force ''%s'' ''%s''"', [NodeZip, NodeDir]),
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
    begin
      MsgBox('Node 运行时解压失败（退出码 ' + IntToStr(ResultCode) + '）。请重新运行安装器。', mbError, MB_OK);
      RaiseException('RUNTIME_EXTRACT_FAILED');
    end;
    // Node zip 解出一层 node-vXX 目录，归位到 runtime\node 根
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Format('-NoProfile -Command "$n = Get-ChildItem ''%s'' -Directory | Select-Object -First 1; if ($n -and $n.Name -like ''node-v*'') { Move-Item ''%s\*'' ''%s'' -Force; Remove-Item $n.FullName }"', [NodeDir, NodeDir + '\' + '$n', NodeDir]),
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
    begin
      MsgBox('Node 目录归位失败（退出码 ' + IntToStr(ResultCode) + '）。', mbError, MB_OK);
      RaiseException('RUNTIME_EXTRACT_FAILED');
    end;
  end;
  if CurStep = ssPostInstall then
  begin
    // 离线安装 AideanFleet wheel + 依赖到私有 Python（修复 N2：pip 失败曾被静默吞掉，wheelhouse 缺失也报“安装成功”）
    if not Exec(ExpandConstant('{app}\runtime\python\python.exe'),
      Format('-m pip install --no-index --find-links "%s" aideanfleet',
             [ExpandConstant('{app}\wheelhouse')]),
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
    begin
      MsgBox('核心组件安装失败（pip 退出码 ' + IntToStr(ResultCode) + '）。请重新运行安装器；若持续失败请检查安装包完整性。', mbError, MB_OK);
      RaiseException('PIP_INSTALL_FAILED');
    end;
  end;
end;

[Icons]
Name: "{autoprograms}\AideanFleet"; Filename: "{app}\launcher.cmd"; Comment: "启动 AideanFleet 控制台"
Name: "{autodesktop}\AideanFleet"; Filename: "{app}\launcher.cmd"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："
Name: "keptata"; Description: "卸载时删除任务数据（默认保留 %LOCALAPPDATA%\AideanFleet\data）"; GroupDescription: "附加任务：" Flags: unchecked

[Run]
Filename: "{app}\launcher.cmd"; Description: "立即启动 AideanFleet（打开浏览器 /setup）"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载清理安装目录；用户数据默认保留（A-13 / DESIGN-001）
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\_packages"
Type: filesandordirs; Name: "{app}\wheelhouse"
Type: filesandordirs; Name: "{app}\fleet"
