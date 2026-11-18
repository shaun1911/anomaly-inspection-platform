using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace AipStation
{
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new StationForm());
        }
    }

    internal class StationConfig
    {
        public string Server = "http://127.0.0.1:8100";
        public string Token = "";
        public string Station = "S1";
        public string Code = "VPTXDF-18B955-CP";
        public string Batch = "";
        public string WatchDir = "";

        public static string ConfigPath
        {
            get { return Path.Combine(Application.StartupPath, "station-config.json"); }
        }

        public static StationConfig Load()
        {
            return ConfigStore.LoadFrom(ConfigPath);
        }

        public void Save()
        {
            File.WriteAllText(ConfigPath, new JavaScriptSerializer().Serialize(this), Encoding.UTF8);
        }
    }

    internal class ApiException : Exception
    {
        public ApiException(string message) : base(message) { }
    }

    internal static class JsonUtil
    {
        public static object Get(object dict, string key)
        {
            var d = dict as Dictionary<string, object>;
            if (d == null) return null;
            object value;
            return d.TryGetValue(key, out value) ? value : null;
        }

        public static string Str(object dict, string key)
        {
            var v = Get(dict, key);
            return v == null ? "" : Convert.ToString(v);
        }

        public static double Num(object dict, string key, double fallback)
        {
            var v = Get(dict, key);
            if (v == null) return fallback;
            double d;
            return double.TryParse(Convert.ToString(v), out d) ? d : fallback;
        }

        public static int Int(object dict, string key, int fallback)
        {
            var v = Get(dict, key);
            if (v == null) return fallback;
            int i;
            return int.TryParse(Convert.ToString(v), out i) ? i : fallback;
        }
    }

    internal class ApiClient
    {
        private readonly HttpClient _http;
        private readonly JavaScriptSerializer _json = new JavaScriptSerializer();
        public string BaseUrl { get; private set; }
        public string Token { get; set; }

        public ApiClient(string baseUrl, string token)
        {
            BaseUrl = (baseUrl ?? "").TrimEnd('/');
            Token = token ?? "";
            _http = new HttpClient();
            _http.Timeout = TimeSpan.FromSeconds(60);
        }

        private HttpRequestMessage Request(HttpMethod method, string path)
        {
            var req = new HttpRequestMessage(method, BaseUrl + path);
            if (!string.IsNullOrEmpty(Token)) req.Headers.Add("X-Station-Token", Token);
            return req;
        }

        private async Task<Dictionary<string, object>> Handle(HttpResponseMessage resp)
        {
            string text = await resp.Content.ReadAsStringAsync();
            if (!resp.IsSuccessStatusCode)
            {
                string message = "HTTP " + (int)resp.StatusCode;
                string action = "";
                try
                {
                    var err = _json.Deserialize<Dictionary<string, object>>(text);
                    if (err != null)
                    {
                        message = JsonUtil.Str(err, "message");
                        action = JsonUtil.Str(err, "action");
                    }
                }
                catch { }
                if (!string.IsNullOrEmpty(action)) message += "（" + action + "）";
                throw new ApiException(message);
            }
            return _json.Deserialize<Dictionary<string, object>>(text);
        }

        public async Task<Dictionary<string, object>> GetAsync(string path)
        {
            using (var req = Request(HttpMethod.Get, path))
            using (var resp = await _http.SendAsync(req))
                return await Handle(resp);
        }

        public async Task<Dictionary<string, object>> PostJsonAsync(string path, object body)
        {
            using (var req = Request(HttpMethod.Post, path))
            {
                req.Content = new StringContent(_json.Serialize(body), Encoding.UTF8, "application/json");
                using (var resp = await _http.SendAsync(req))
                    return await Handle(resp);
            }
        }

        public async Task<Dictionary<string, object>> PostMultipartAsync(
            string path, Dictionary<string, string> fields, string filePath)
        {
            using (var req = Request(HttpMethod.Post, path))
            using (var form = new MultipartFormDataContent())
            {
                foreach (var pair in fields)
                    form.Add(new StringContent(pair.Value ?? "", Encoding.UTF8), pair.Key);
                var bytes = File.ReadAllBytes(filePath);
                var file = new ByteArrayContent(bytes);
                file.Headers.ContentType = new MediaTypeHeaderValue("image/png");
                form.Add(file, "image", Path.GetFileName(filePath));
                req.Content = form;
                using (var resp = await _http.SendAsync(req))
                    return await Handle(resp);
            }
        }
    }

    internal class ReportDialog : Form
    {
        private readonly ComboBox _expected;
        private readonly ComboBox _reason;
        private readonly TextBox _note;

        public string ExpectedVerdict { get { return _expected.SelectedItem.ToString(); } }
        public string ReasonCode { get { return _reason.SelectedItem.ToString(); } }
        public string Note { get { return _note.Text.Trim(); } }

        public ReportDialog(string systemLabel)
        {
            Text = "误判上报";
            StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            ClientSize = new Size(420, 260);
            Font = new Font("Microsoft YaHei UI", 9f);

            var lbl1 = new Label { Text = "现场结论", Left = 20, Top = 24, Width = 90 };
            _expected = new ComboBox { Left = 120, Top = 20, Width = 260, DropDownStyle = ComboBoxStyle.DropDownList };
            _expected.Items.Add("ok");
            _expected.Items.Add("ng");
            _expected.SelectedItem = systemLabel == "ok" ? "ng" : "ok";

            var lbl2 = new Label { Text = "理由", Left = 20, Top = 70, Width = 90 };
            _reason = new ComboBox { Left = 120, Top = 66, Width = 260, DropDownStyle = ComboBoxStyle.DropDownList };
            _reason.Items.AddRange(new object[] { "漏检", "误报", "划伤", "脏污", "压伤", "其他" });
            _reason.SelectedIndex = 0;

            var lbl3 = new Label { Text = "备注", Left = 20, Top = 116, Width = 90 };
            _note = new TextBox { Left = 120, Top = 112, Width = 260, Height = 48, Multiline = true };

            var ok = new Button { Text = "提交上报", Left = 120, Top = 190, Width = 120, Height = 34, DialogResult = DialogResult.OK };
            var cancel = new Button { Text = "取消", Left = 260, Top = 190, Width = 120, Height = 34, DialogResult = DialogResult.Cancel };

            Controls.Add(lbl1); Controls.Add(_expected);
            Controls.Add(lbl2); Controls.Add(_reason);
            Controls.Add(lbl3); Controls.Add(_note);
            Controls.Add(ok); Controls.Add(cancel);
            AcceptButton = ok;
            CancelButton = cancel;
        }
    }

    internal class StationForm : Form
    {
        private readonly TextBox _txtServer;
        private readonly TextBox _txtToken;
        private readonly TextBox _txtStation;
        private readonly TextBox _txtCode;
        private readonly TextBox _txtBatch;
        private readonly Label _lblStatus;
        private readonly Label _lblConfig;
        private readonly Label _lblPending;
        private readonly PictureBox _image;
        private readonly Label _lblResult;
        private readonly Label _lblDetail;
        private readonly DataGridView _history;
        private readonly Button _btnReport;
        private readonly Button _btnReviewOk;
        private readonly Button _btnReviewNg;
        private readonly Button _btnWatch;
        private readonly Button _btnOpen;
        private readonly Button _btnPlc;
        private PlcConfig _plcCfg;
        private PlcController _plcController;
        private readonly Timer _heartbeat;
        private readonly Timer _pendingTimer;
        private FileSystemWatcher _watcher;
        private ApiClient _api;
        private StationConfig _cfg;
        private Dictionary<string, object> _stationCfg;
        private int[] _roi;
        private int _resultId;
        private string _resultLabel;
        private double _resultScore;
        private bool _processing;
        private readonly JavaScriptSerializer _json = new JavaScriptSerializer();

        public StationForm()
        {
            Text = "AIP 工位客户端";
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(1280, 820);
            MinimumSize = new Size(1100, 700);
            Font = new Font("Microsoft YaHei UI", 9f);

            _cfg = StationConfig.Load();

            var top = new Panel { Dock = DockStyle.Top, Height = 140, BackColor = Color.FromArgb(247, 248, 250) };

            top.Controls.Add(MakeLabel("服务器", 12, 14));
            _txtServer = MakeText(_cfg.Server, 70, 10, 230);
            top.Controls.Add(_txtServer);
            top.Controls.Add(MakeLabel("令牌", 312, 14, 36));
            _txtToken = MakeText(_cfg.Token, 350, 10, 140);
            _txtToken.UseSystemPasswordChar = true;
            top.Controls.Add(_txtToken);
            top.Controls.Add(MakeLabel("站位", 505, 14, 36));
            _txtStation = MakeText(_cfg.Station, 545, 10, 70);
            top.Controls.Add(_txtStation);
            top.Controls.Add(MakeLabel("编码", 625, 14, 36));
            _txtCode = MakeText(_cfg.Code, 665, 10, 200);
            top.Controls.Add(_txtCode);
            top.Controls.Add(MakeLabel("批次", 875, 14, 36));
            _txtBatch = MakeText(_cfg.Batch, 915, 10, 100);
            top.Controls.Add(_txtBatch);

            var btnConnect = MakeButton("连接 / 换型", 1025, 8, 110);
            btnConnect.Click += async (s, e) => await ConnectAsync(true);
            top.Controls.Add(btnConnect);
            var btnPlcCfg = MakeButton("PLC 设置", 1145, 8, 80);
            btnPlcCfg.Click += (s, e) => OpenPlcSettings();
            top.Controls.Add(btnPlcCfg);

            _lblStatus = new Label { Left = 12, Top = 52, Width = 700, Height = 24, Text = "未连接", ForeColor = Color.FromArgb(90, 96, 104) };
            top.Controls.Add(_lblStatus);
            _lblConfig = new Label { Left = 12, Top = 78, Width = 760, Height = 24, Text = "尚未换型", ForeColor = Color.FromArgb(90, 96, 104) };
            top.Controls.Add(_lblConfig);
            _lblPending = new Label { Left = 12, Top = 104, Width = 400, Height = 24, Text = "待复核：-", ForeColor = Color.FromArgb(90, 96, 104) };
            top.Controls.Add(_lblPending);

            _btnOpen = MakeButton("打开图片", 430, 100, 100);
            _btnOpen.Click += (s, e) => OpenImage();
            top.Controls.Add(_btnOpen);
            _btnWatch = MakeButton("监听目录", 540, 100, 100);
            _btnWatch.Click += (s, e) => ToggleWatch();
            top.Controls.Add(_btnWatch);
            var btnChooseDir = MakeButton("选择监听目录", 650, 100, 120);
            btnChooseDir.Click += (s, e) => ChooseWatchDir();
            top.Controls.Add(btnChooseDir);
            var btnAdmin = MakeButton("后台", 780, 100, 70);
            btnAdmin.Click += (s, e) => OpenAdmin();
            top.Controls.Add(btnAdmin);
            _btnPlc = MakeButton("PLC 连接", 860, 100, 100);
            _btnPlc.Click += (s, e) => TogglePlc();
            top.Controls.Add(_btnPlc);

            var split = new SplitContainer { Dock = DockStyle.Fill, SplitterDistance = 700 };
            var imagePanel = split.Panel1;
            _image = new PictureBox { Dock = DockStyle.Fill, SizeMode = PictureBoxSizeMode.Zoom, BackColor = Color.FromArgb(32, 34, 38) };
            imagePanel.Controls.Add(_image);

            var right = split.Panel2;
            _lblResult = new Label
            {
                Dock = DockStyle.Top, Height = 110, Text = "等待判定", TextAlign = ContentAlignment.MiddleCenter,
                Font = new Font("Microsoft YaHei UI", 34f, FontStyle.Bold), BackColor = Color.FromArgb(235, 237, 241),
                ForeColor = Color.FromArgb(60, 64, 72)
            };
            _lblDetail = new Label
            {
                Dock = DockStyle.Top, Height = 90, Padding = new Padding(10, 6, 10, 6),
                Text = "放入图片或选择文件后开始判定。", Font = new Font("Microsoft YaHei UI", 10f)
            };
            var actions = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 96, Padding = new Padding(6) };
            _btnReviewOk = MakeButton("复核判 OK", 0, 0, 100);
            _btnReviewOk.Click += async (s, e) => await ReviewAsync("ok");
            _btnReviewNg = MakeButton("复核判 NG", 0, 0, 100);
            _btnReviewNg.Click += async (s, e) => await ReviewAsync("ng");
            _btnReport = MakeButton("误判上报", 0, 0, 100);
            _btnReport.Click += async (s, e) => await ReportAsync();
            _btnReviewOk.Enabled = false;
            _btnReviewNg.Enabled = false;
            _btnReport.Enabled = false;
            actions.Controls.Add(_btnReviewOk);
            actions.Controls.Add(_btnReviewNg);
            actions.Controls.Add(_btnReport);

            _history = new DataGridView
            {
                Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false,
                AllowUserToDeleteRows = false, RowHeadersVisible = false,
                AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
                SelectionMode = DataGridViewSelectionMode.FullRowSelect
            };
            _history.Columns.Add("time", "时间");
            _history.Columns.Add("part", "件号");
            _history.Columns.Add("label", "结果");
            _history.Columns.Add("score", "分数");
            _history.Columns.Add("action", "动作");

            right.Controls.Add(_history);
            right.Controls.Add(actions);
            right.Controls.Add(_lblDetail);
            right.Controls.Add(_lblResult);

            Controls.Add(split);
            Controls.Add(top);

            _heartbeat = new Timer { Interval = 10000 };
            _heartbeat.Tick += async (s, e) => await HeartbeatAsync();
            _pendingTimer = new Timer { Interval = 15000 };
            _pendingTimer.Tick += async (s, e) => await RefreshPendingAsync();
            _heartbeat.Start();
            _pendingTimer.Start();

            FormClosing += (s, e) => SaveConfig();
            Shown += async (s, e) => {
                _txtServer.Select(0, 0); _txtToken.Select(0, 0); _txtStation.Select(0, 0); _txtCode.Select(0, 0); _txtBatch.Select(0, 0);
                await ConnectAsync(false);
                if (!string.IsNullOrEmpty(_cfg.WatchDir)) ToggleWatch();
            };
        }

        private static Label MakeLabel(string text, int x, int y, int width = 56)
        {
            return new Label { Text = text, Left = x, Top = y, Width = width, Height = 22 };
        }

        private static TextBox MakeText(string text, int x, int y, int width)
        {
            return new TextBox { Text = text ?? "", Left = x, Top = y, Width = width, Height = 24 };
        }

        private static Button MakeButton(string text, int x, int y, int width)
        {
            return new Button { Text = text, Left = x, Top = y, Width = width, Height = 34, Margin = new Padding(4) };
        }

        private string ConfigPath
        {
            get { return Path.Combine(Application.StartupPath, "station-config.json"); }
        }

        private void LoadConfig()
        {
            _cfg = StationConfig.Load();
        }

        private void SaveConfig()
        {
            try
            {
                _cfg.Server = _txtServer.Text.Trim();
                _cfg.Token = _txtToken.Text.Trim();
                _cfg.Station = _txtStation.Text.Trim();
                _cfg.Code = _txtCode.Text.Trim();
                _cfg.Batch = _txtBatch.Text.Trim();
                _cfg.Save();
            }
            catch { }
        }

        private async Task ConnectAsync(bool notify)
        {
            try
            {
                SaveConfig();
                _api = new ApiClient(_cfg.Server, _cfg.Token);
                var health = await _api.GetAsync("/health");
                if (JsonUtil.Str(health, "status") != "ok") throw new ApiException("服务端状态异常");
                if (string.IsNullOrEmpty(_cfg.Code)) throw new ApiException("请先填编码");
                await SwitchCodeAsync();
                _lblStatus.Text = "已连接 " + _cfg.Server + " · 站位 " + _cfg.Station;
                _lblStatus.ForeColor = Color.FromArgb(20, 122, 50);
                if (notify) MessageBox.Show(this, "连接成功，已换型到 " + _cfg.Code, "AIP", MessageBoxButtons.OK, MessageBoxIcon.Information);
                await RefreshPendingAsync();
            }
            catch (Exception ex)
            {
                _lblStatus.Text = "连接失败：" + ex.Message;
                _lblStatus.ForeColor = Color.FromArgb(198, 40, 40);
                if (notify) MessageBox.Show(this, ex.Message, "连接失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private async Task SwitchCodeAsync()
        {
            _cfg.Code = _txtCode.Text.Trim();
            _stationCfg = await _api.GetAsync("/station/config?code=" + Uri.EscapeDataString(_cfg.Code));
            _roi = null;
            var roiObj = JsonUtil.Get(_stationCfg, "roi_rect") as System.Collections.IEnumerable;
            if (roiObj != null)
            {
                var values = new List<int>();
                foreach (var v in roiObj) values.Add(Convert.ToInt32(v));
                if (values.Count == 4) _roi = values.ToArray();
            }
            var threshold = JsonUtil.Get(_stationCfg, "threshold") as Dictionary<string, object>;
            _lblConfig.Text = string.Format("模型 {0} v{1} · ROI {2} · 阈值 {3} / {4}",
                JsonUtil.Str(_stationCfg, "model_code"), JsonUtil.Str(_stationCfg, "version_no"),
                _roi == null ? "-" : string.Join(",", _roi),
                threshold == null ? "-" : JsonUtil.Num(threshold, "th_lo", 0).ToString("0.000"),
                threshold == null ? "-" : JsonUtil.Num(threshold, "th_hi", 0).ToString("0.000"));
            SaveConfig();
        }

        private void OpenAdmin()
        {
            try { System.Diagnostics.Process.Start(_cfg.Server.TrimEnd('/') + "/admin"); }
            catch (Exception ex) { MessageBox.Show(this, ex.Message, "打开后台失败"); }
        }

        private void ChooseWatchDir()
        {
            using (var dlg = new FolderBrowserDialog())
            {
                if (dlg.ShowDialog(this) == DialogResult.OK)
                {
                    _cfg.WatchDir = dlg.SelectedPath;
                    SaveConfig();
                    _lblStatus.Text = "监听目录：" + _cfg.WatchDir;
                }
            }
        }

        private void ToggleWatch()
        {
            if (_watcher != null)
            {
                _watcher.EnableRaisingEvents = false;
                _watcher.Dispose();
                _watcher = null;
                _btnWatch.Text = "监听目录";
                _lblStatus.Text = "已停止监听";
                return;
            }
            string dir = _cfg.WatchDir;
            if (string.IsNullOrEmpty(dir))
            {
                ChooseWatchDir();
                dir = _cfg.WatchDir;
            }
            if (string.IsNullOrEmpty(dir)) return;
            Directory.CreateDirectory(dir);
            _watcher = new FileSystemWatcher(dir);
            _watcher.Created += (s, e) => { if (IsImage(e.FullPath)) BeginInvoke(new Action(async () => await ProcessImageAsync(e.FullPath))); };
            _watcher.EnableRaisingEvents = true;
            _btnWatch.Text = "停止监听";
            _lblStatus.Text = "监听中：" + dir;
        }

        private static bool IsImage(string path)
        {
            string ext = Path.GetExtension(path).ToLowerInvariant();
            return ext == ".png" || ext == ".jpg" || ext == ".jpeg" || ext == ".bmp" || ext == ".webp";
        }

        private void OpenImage()
        {
            using (var dlg = new OpenFileDialog())
            {
                dlg.Filter = "图片|*.png;*.jpg;*.jpeg;*.bmp;*.webp|所有文件|*.*";
                if (dlg.ShowDialog(this) == DialogResult.OK)
                {
                    var path = dlg.FileName;
                    BeginInvoke(new Action(async () => await ProcessImageAsync(path)));
                }
            }
        }

        private async Task<int> ProcessImageAsync(string path)
        {
            if (_processing) return 3;
            if (_api == null) { MessageBox.Show(this, "先点「连接 / 换型」", "AIP"); return 3; }
            if (_stationCfg == null) { MessageBox.Show(this, "先换型", "AIP"); return 3; }
            _processing = true;
            _btnReport.Enabled = false;
            _btnReviewOk.Enabled = false;
            _btnReviewNg.Enabled = false;
            SetResult("判定中…", Color.FromArgb(235, 237, 241), Color.FromArgb(60, 64, 72));
            string temp = null;
            try
            {
                using (var src = Image.FromFile(path))
                {
                    Rectangle rect = _roi == null ? new Rectangle(0, 0, src.Width, src.Height) : new Rectangle(_roi[0], _roi[1], _roi[2] - _roi[0], _roi[3] - _roi[1]);
                    if (rect.X < 0 || rect.Y < 0 || rect.Right > src.Width || rect.Bottom > src.Height)
                        throw new ApiException("ROI 超出图片范围：" + rect);
                    using (var crop = new Bitmap(rect.Width, rect.Height))
                    {
                        using (var g = Graphics.FromImage(crop))
                            g.DrawImage(src, new Rectangle(0, 0, rect.Width, rect.Height), rect, GraphicsUnit.Pixel);
                        _image.Image = new Bitmap(crop);
                        temp = Path.Combine(Path.GetTempPath(), "aip-" + Guid.NewGuid().ToString("N") + ".png");
                        crop.Save(temp, ImageFormat.Png);
                    }
                }
                string part = Path.GetFileNameWithoutExtension(path);
                string batch = string.IsNullOrEmpty(_cfg.Batch) ? "B-" + DateTime.Now.ToString("yyyyMMdd") : _cfg.Batch;
                var fields = new Dictionary<string, string>
                {
                    { "code", _cfg.Code },
                    { "station", _cfg.Station },
                    { "part_no", part },
                    { "batch_no", batch }
                };
                var resp = await _api.PostMultipartAsync("/infer?sync=1", fields, temp);
                if (JsonUtil.Str(resp, "status") != "done") throw new ApiException("服务端未返回完成结果");
                var result = JsonUtil.Get(resp, "result") as Dictionary<string, object>;
                var decision = JsonUtil.Get(resp, "decision") as Dictionary<string, object>;
                _resultId = JsonUtil.Int(result, "id", 0);
                _resultLabel = JsonUtil.Str(result, "label");
                _resultScore = JsonUtil.Num(result, "score", 0);
                string action = decision == null ? "" : JsonUtil.Str(decision, "action");
                string why = decision == null ? "" : JsonUtil.Str(decision, "reason");
                Color back = _resultLabel == "ok" ? Color.FromArgb(225, 245, 230) : _resultLabel == "ng" ? Color.FromArgb(252, 228, 228) : Color.FromArgb(255, 244, 214);
                Color fore = _resultLabel == "ok" ? Color.FromArgb(20, 122, 50) : _resultLabel == "ng" ? Color.FromArgb(198, 40, 40) : Color.FromArgb(168, 100, 0);
                SetResult(_resultLabel == "ok" ? "OK 放行" : _resultLabel == "ng" ? "NG 拦截" : "灰区 需人工", back, fore);
                _lblDetail.Text = string.Format("件号 {0} · 分数 {1:0.000} · 决策 {2}{3}\n结果 #{4} · 模型版本 {5}",
                    part, _resultScore, action, string.IsNullOrEmpty(why) ? "" : "（" + why + "）",
                    _resultId, JsonUtil.Str(resp, "model_version_id"));
                _btnReport.Enabled = true;
                _btnReviewOk.Enabled = true;
                _btnReviewNg.Enabled = true;
                _history.Rows.Insert(0, DateTime.Now.ToString("HH:mm:ss"), part, _resultLabel, _resultScore.ToString("0.000"), action);
                await RefreshPendingAsync();
                return _resultLabel == "ok" ? 0 : _resultLabel == "ng" ? 1 : 2;
            }
            catch (Exception ex)
            {
                SetResult("判定失败", Color.FromArgb(252, 228, 228), Color.FromArgb(198, 40, 40));
                _lblDetail.Text = ex.Message;
                return 3;
            }
            finally
            {
                if (temp != null) try { File.Delete(temp); } catch { }
                _processing = false;
            }
        }

        private void SetResult(string text, Color back, Color fore)
        {
            _lblResult.Text = text;
            _lblResult.BackColor = back;
            _lblResult.ForeColor = fore;
        }

        private async Task ReviewAsync(string verdict)
        {
            if (_resultId <= 0) return;
            try
            {
                await _api.PostJsonAsync("/review/" + _resultId + "/confirm", new
                {
                    verdict = verdict,
                    note = "工位复核",
                    confirmed_by = _cfg.Station
                });
                SetResult(verdict == "ok" ? "复核 OK" : "复核 NG", Color.FromArgb(235, 237, 241), Color.FromArgb(60, 64, 72));
                _lblDetail.Text = "结果 #" + _resultId + " 已复核为 " + verdict.ToUpperInvariant();
                _btnReviewOk.Enabled = false;
                _btnReviewNg.Enabled = false;
                _btnReport.Enabled = false;
                await RefreshPendingAsync();
            }
            catch (Exception ex) { MessageBox.Show(this, ex.Message, "复核失败", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        }

        private async Task ReportAsync()
        {
            if (_resultId <= 0) return;
            using (var dlg = new ReportDialog(_resultLabel))
            {
                if (dlg.ShowDialog(this) != DialogResult.OK) return;
                try
                {
                    await _api.PostJsonAsync("/station/misjudge", new
                    {
                        result_id = _resultId,
                        expected_verdict = dlg.ExpectedVerdict,
                        reason_code = dlg.ReasonCode,
                        note = dlg.Note,
                        station = _cfg.Station,
                        reported_by = _cfg.Station
                    });
                    MessageBox.Show(this, "已上报，等待后台处理。", "误判上报", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    _btnReport.Enabled = false;
                }
                catch (Exception ex) { MessageBox.Show(this, ex.Message, "上报失败", MessageBoxButtons.OK, MessageBoxIcon.Error); }
            }
        }

        private void OpenPlcSettings()
        {
            _plcCfg = PlcConfig.Load();
            using (var dlg = new PlcConfigDialog(_plcCfg))
            {
                if (dlg.ShowDialog(this) == DialogResult.OK)
                {
                    _plcCfg = dlg.Config;
                    _lblStatus.Text = "PLC 配置已保存：" + _plcCfg.Protocol;
                }
            }
        }

        private void TogglePlc()
        {
            if (_plcController != null)
            {
                try { _plcController.Dispose(); } catch { }
                _plcController = null;
                _btnPlc.Text = "PLC 连接";
                _lblStatus.Text = "PLC 已断开";
                return;
            }
            try
            {
                if (string.IsNullOrEmpty(_cfg.WatchDir))
                    _cfg.WatchDir = Path.Combine(Application.StartupPath, "watch");
                Directory.CreateDirectory(_cfg.WatchDir);
                if (_watcher != null) ToggleWatch();
                _plcCfg = PlcConfig.Load();
                IPlcAdapter adapter = _plcCfg.Protocol == "S7"
                    ? (IPlcAdapter)new SiemensS7Adapter(_plcCfg)
                    : new ModbusRtuAdapter(_plcCfg);
                adapter.Connect();
                _plcController = new PlcController(_plcCfg, adapter, _cfg.Code, CaptureForPlc, ProcessImageAsync, ChangeCodeFromPlc, PlcLog);
                _btnPlc.Text = "PLC 断开";
                _lblStatus.Text = "PLC 已连接：" + _plcCfg.Protocol + " · 等待 Trigger";
            }
            catch (Exception ex)
            {
                _lblStatus.Text = "PLC 连接失败：" + ex.Message;
                MessageBox.Show(this, ex.Message, "PLC 连接失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private async Task ChangeCodeFromPlc(string code)
        {
            _txtCode.Text = code;
            await ConnectAsync(false);
        }

        private async Task<string> CaptureForPlc()
        {
            return await CameraWait.WaitForNewImage(_cfg.WatchDir, DateTime.UtcNow.AddMilliseconds(-200), _plcCfg.CameraTimeoutMs);
        }

        private void PlcLog(string msg)
        {
            if (IsDisposed) return;
            try { BeginInvoke(new Action(() => { _lblStatus.Text = msg; })); } catch { }
        }

        private async Task HeartbeatAsync()
        {
            if (_api == null || _stationCfg == null) return;
            try
            {
                await _api.PostJsonAsync("/station/heartbeat", new
                {
                    station = _cfg.Station,
                    config_rev = JsonUtil.Int(_stationCfg, "roi_rev", 0)
                });
            }
            catch { }
        }

        private async Task RefreshPendingAsync()
        {
            if (_api == null) return;
            try
            {
                var q = await _api.GetAsync("/review/pending?station=" + Uri.EscapeDataString(_cfg.Station) + "&limit=50");
                _lblPending.Text = "待复核：" + JsonUtil.Int(q, "count", 0) + " 件";
            }
            catch { }
        }
    }

    internal static class ConfigStore
    {
        public static StationConfig LoadFrom(string path)
        {
            try
            {
                if (File.Exists(path))
                {
                    var text = File.ReadAllText(path, Encoding.UTF8);
                    var cfg = new JavaScriptSerializer().Deserialize<StationConfig>(text);
                    if (cfg != null) return cfg;
                }
            }
            catch { }
            return new StationConfig();
        }
    }
}
