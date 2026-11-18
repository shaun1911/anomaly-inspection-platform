using System;
using System.Drawing;
using System.Windows.Forms;

namespace AipStation
{
    internal class PlcConfigDialog : Form
    {
        private readonly ComboBox _protocol;
        private readonly TextBox _port, _baud, _parity, _dataBits, _stopBits, _slave;
        private readonly TextBox _ip, _rack, _slot, _timeout;
        private readonly TextBox _ready, _trigger, _busy, _done, _error, _result;
        public PlcConfig Config { get; private set; }

        public PlcConfigDialog(PlcConfig cfg)
        {
            Config = cfg;
            Text = "PLC 设置";
            StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false; MinimizeBox = false;
            ClientSize = new Size(620, 620);
            Font = new Font("Microsoft YaHei UI", 9f);

            int y = 16;
            AddLabel("协议", 20, y);
            _protocol = new ComboBox { Left = 110, Top = y - 3, Width = 180, DropDownStyle = ComboBoxStyle.DropDownList };
            _protocol.Items.Add("ModbusRtu"); _protocol.Items.Add("S7");
            _protocol.SelectedItem = cfg.Protocol == "S7" ? "S7" : "ModbusRtu";
            Controls.Add(_protocol);
            y += 36;

            AddLabel("串口", 20, y); _port = AddText(cfg.PortName, 110, y);
            AddLabel("波特率", 330, y); _baud = AddText(cfg.BaudRate.ToString(), 400, y);
            y += 36;
            AddLabel("校验", 20, y); _parity = AddText(cfg.Parity, 110, y);
            AddLabel("数据位", 330, y); _dataBits = AddText(cfg.DataBits.ToString(), 400, y);
            y += 36;
            AddLabel("停止位", 20, y); _stopBits = AddText(cfg.StopBits, 110, y);
            AddLabel("从站", 330, y); _slave = AddText(cfg.SlaveId.ToString(), 400, y);
            y += 36;

            AddLabel("S7 IP", 20, y); _ip = AddText(cfg.S7Ip, 110, y);
            AddLabel("Rack", 330, y); _rack = AddText(cfg.Rack.ToString(), 400, y);
            y += 36;
            AddLabel("Slot", 20, y); _slot = AddText(cfg.Slot.ToString(), 110, y);
            AddLabel("相机超时ms", 330, y); _timeout = AddText(cfg.CameraTimeoutMs.ToString(), 430, y);
            y += 40;

            AddLabel("Ready", 20, y); _ready = AddText(cfg.Ready, 110, y);
            AddLabel("Trigger", 330, y); _trigger = AddText(cfg.Trigger, 410, y);
            y += 36;
            AddLabel("Busy", 20, y); _busy = AddText(cfg.Busy, 110, y);
            AddLabel("Done", 330, y); _done = AddText(cfg.Done, 410, y);
            y += 36;
            AddLabel("Error", 20, y); _error = AddText(cfg.Error, 110, y);
            AddLabel("Result", 330, y); _result = AddText(cfg.Result, 410, y);

            var ok = new Button { Text = "保存", Left = 360, Top = 560, Width = 100, Height = 34, DialogResult = DialogResult.OK };
            var cancel = new Button { Text = "取消", Left = 470, Top = 560, Width = 100, Height = 34, DialogResult = DialogResult.Cancel };
            Controls.Add(ok); Controls.Add(cancel);
            AcceptButton = ok; CancelButton = cancel;
        }

        private void AddLabel(string text, int x, int y)
        {
            Controls.Add(new Label { Text = text, Left = x, Top = y, Width = 80, Height = 22 });
        }

        private TextBox AddText(string value, int x, int y)
        {
            var box = new TextBox { Text = value ?? "", Left = x, Top = y - 3, Width = 200, Height = 24 };
            Controls.Add(box);
            return box;
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (DialogResult == DialogResult.OK)
            {
                try
                {
                    Config.Protocol = _protocol.SelectedItem.ToString();
                    Config.PortName = _port.Text.Trim();
                    Config.BaudRate = int.Parse(_baud.Text.Trim());
                    Config.Parity = _parity.Text.Trim();
                    Config.DataBits = int.Parse(_dataBits.Text.Trim());
                    Config.StopBits = _stopBits.Text.Trim();
                    Config.SlaveId = int.Parse(_slave.Text.Trim());
                    Config.S7Ip = _ip.Text.Trim();
                    Config.Rack = int.Parse(_rack.Text.Trim());
                    Config.Slot = int.Parse(_slot.Text.Trim());
                    Config.CameraTimeoutMs = int.Parse(_timeout.Text.Trim());
                    Config.Ready = _ready.Text.Trim();
                    Config.Trigger = _trigger.Text.Trim();
                    Config.Busy = _busy.Text.Trim();
                    Config.Done = _done.Text.Trim();
                    Config.Error = _error.Text.Trim();
                    Config.Result = _result.Text.Trim();
                    Config.Save();
                }
                catch (Exception ex)
                {
                    MessageBox.Show(this, "配置无效：" + ex.Message, "PLC 设置", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    e.Cancel = true;
                }
            }
            base.OnFormClosing(e);
        }
    }
}
