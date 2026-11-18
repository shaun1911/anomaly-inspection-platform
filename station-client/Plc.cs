using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Ports;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Sharp7;
using System.Windows.Forms;

namespace AipStation
{
    internal class PlcConfig
    {
        public bool Enabled = false;
        public string Protocol = "ModbusRtu";   // ModbusRtu | S7
        public string PortName = "COM1";
        public int BaudRate = 9600;
        public string Parity = "None";
        public int DataBits = 8;
        public string StopBits = "One";
        public int SlaveId = 1;

        public string S7Ip = "192.168.0.10";
        public int Rack = 0;
        public int Slot = 1;

        public string Ready = "0";
        public string Trigger = "1";
        public string Busy = "2";
        public string Done = "3";
        public string Error = "4";
        public string Result = "100";

        public int CameraTimeoutMs = 3000;

        public static string ConfigPath
        {
            get { return Path.Combine(Application.StartupPath, "plc-config.json"); }
        }

        public static PlcConfig Load()
        {
            try
            {
                if (File.Exists(ConfigPath))
                {
                    var cfg = new System.Web.Script.Serialization.JavaScriptSerializer()
                        .Deserialize<PlcConfig>(File.ReadAllText(ConfigPath, Encoding.UTF8));
                    if (cfg != null) return cfg;
                }
            }
            catch { }
            return new PlcConfig();
        }

        public void Save()
        {
            File.WriteAllText(ConfigPath,
                new System.Web.Script.Serialization.JavaScriptSerializer().Serialize(this), Encoding.UTF8);
        }
    }

    internal interface IPlcAdapter : IDisposable
    {
        bool IsConnected { get; }
        void Connect();
        bool ReadBool(string address);
        int ReadInt(string address);
        void WriteBool(string address, bool value);
        void WriteInt(string address, int value);
    }

    internal class PlcException : Exception
    {
        public PlcException(string message) : base(message) { }
    }

    internal static class ModbusCrc
    {
        public static ushort Calc(byte[] data, int length)
        {
            ushort crc = 0xFFFF;
            for (int i = 0; i < length; i++)
            {
                crc ^= data[i];
                for (int b = 0; b < 8; b++)
                {
                    if ((crc & 1) != 0) crc = (ushort)((crc >> 1) ^ 0xA001);
                    else crc >>= 1;
                }
            }
            return crc;
        }
    }

    internal class ModbusRtuAdapter : IPlcAdapter
    {
        private readonly PlcConfig _cfg;
        private SerialPort _port;
        private readonly object _lock = new object();

        public ModbusRtuAdapter(PlcConfig cfg) { _cfg = cfg; }

        public bool IsConnected { get { return _port != null && _port.IsOpen; } }

        public void Connect()
        {
            Close();
            var parity = (Parity)Enum.Parse(typeof(Parity), _cfg.Parity, true);
            var stop = (StopBits)Enum.Parse(typeof(StopBits), _cfg.StopBits, true);
            _port = new SerialPort(_cfg.PortName, _cfg.BaudRate, parity, _cfg.DataBits, stop);
            _port.ReadTimeout = 800;
            _port.WriteTimeout = 800;
            _port.Open();
        }

        private byte[] Transaction(byte function, byte[] data)
        {
            if (!IsConnected) throw new PlcException("Modbus RTU 未连接");
            lock (_lock)
            {
                var frame = new byte[data.Length + 4];
                frame[0] = (byte)_cfg.SlaveId;
                frame[1] = function;
                Array.Copy(data, 0, frame, 2, data.Length);
                var crc = ModbusCrc.Calc(frame, frame.Length - 2);
                frame[frame.Length - 2] = (byte)(crc & 0xFF);
                frame[frame.Length - 1] = (byte)(crc >> 8);

                _port.DiscardInBuffer();
                _port.DiscardOutBuffer();
                _port.Write(frame, 0, frame.Length);

                int expected = function == 0x05 || function == 0x06 ? 8 :
                    (function == 0x01 ? 5 + (data[3] + 7) / 8 : 5 + data[3] * 2);
                if (function == 0x03) expected = 5 + data[3] * 2;
                if (function == 0x01) expected = 5 + (data[3] + 7) / 8;

                var resp = new byte[expected];
                int read = 0;
                var deadline = DateTime.UtcNow.AddMilliseconds(900);
                while (read < expected && DateTime.UtcNow < deadline)
                {
                    try { read += _port.Read(resp, read, expected - read); }
                    catch (TimeoutException) { break; }
                }
                if (read < 5) throw new PlcException("Modbus RTU 响应超时");
                if (resp[0] != _cfg.SlaveId) throw new PlcException("Modbus RTU 从站地址不匹配");
                if ((resp[1] & 0x80) != 0) throw new PlcException("Modbus 异常码 " + resp[2]);
                var crc2 = ModbusCrc.Calc(resp, read - 2);
                if ((resp[read - 2] != (byte)(crc2 & 0xFF)) || (resp[read - 1] != (byte)(crc2 >> 8)))
                    throw new PlcException("Modbus RTU CRC 校验失败");
                var body = new byte[Math.Max(0, read - 5)];
                Array.Copy(resp, 3, body, 0, body.Length);
                return body;
            }
        }

        private static byte[] AddrQty(int address, int qty)
        {
            return new byte[] { (byte)(address >> 8), (byte)(address & 0xFF),
                                (byte)(qty >> 8), (byte)(qty & 0xFF) };
        }

        public bool ReadBool(string address)
        {
            int addr = int.Parse(address);
            var body = Transaction(0x01, AddrQty(addr, 1));
            if (body.Length < 1) throw new PlcException("线圈响应为空");
            return (body[0] & 0x01) != 0;
        }

        public void WriteBool(string address, bool value)
        {
            int addr = int.Parse(address);
            var data = new byte[] { (byte)(addr >> 8), (byte)(addr & 0xFF), value ? (byte)0xFF : (byte)0x00, 0x00 };
            Transaction(0x05, data);
        }

        public int ReadInt(string address)
        {
            int addr = int.Parse(address);
            var body = Transaction(0x03, AddrQty(addr, 1));
            if (body.Length < 2) throw new PlcException("保持寄存器响应为空");
            return (body[0] << 8) | body[1];
        }

        public void WriteInt(string address, int value)
        {
            int addr = int.Parse(address);
            var data = new byte[] { (byte)(addr >> 8), (byte)(addr & 0xFF),
                                    (byte)(value >> 8), (byte)(value & 0xFF) };
            Transaction(0x06, data);
        }

        private void Close()
        {
            if (_port == null) return;
            try { if (_port.IsOpen) _port.Close(); } catch { }
            _port.Dispose();
            _port = null;
        }

        public void Dispose() { Close(); }
    }

    internal class S7Tag
    {
        public int Area;
        public int Db;
        public int Start;
        public int Bit;
        public bool IsBool;
        public bool IsDword;
    }

    internal class SiemensS7Adapter : IPlcAdapter
    {
        private readonly PlcConfig _cfg;
        private S7Client _client;

        public SiemensS7Adapter(PlcConfig cfg) { _cfg = cfg; }

        public bool IsConnected { get { return _client != null && _client.Connected; } }

        public void Connect()
        {
            Close();
            _client = new S7Client();
            int res = _client.ConnectTo(_cfg.S7Ip, _cfg.Rack, _cfg.Slot);
            if (res != 0) throw new PlcException("S7 连接失败：" + _client.ErrorText(res));
        }

        private static S7Tag Parse(string address)
        {
            var tag = new S7Tag();
            string s = address.Trim().ToUpperInvariant();
            if (s.StartsWith("DB"))
            {
                int dot = s.IndexOf('.');
                tag.Area = S7Consts.S7AreaDB;
                tag.Db = int.Parse(s.Substring(2, dot - 2));
                string rest = s.Substring(dot + 1);
                if (rest.StartsWith("DBX"))
                {
                    tag.IsBool = true;
                    var parts = rest.Substring(3).Split('.');
                    tag.Start = int.Parse(parts[0]);
                    tag.Bit = int.Parse(parts[1]);
                }
                else if (rest.StartsWith("DBW")) { tag.Start = int.Parse(rest.Substring(3)); }
                else if (rest.StartsWith("DBD")) { tag.Start = int.Parse(rest.Substring(3)); tag.IsDword = true; }
                else throw new PlcException("不支持的 S7 地址：" + address);
                return tag;
            }
            if (s.StartsWith("M") || s.StartsWith("I") || s.StartsWith("Q"))
            {
                tag.Area = s[0] == 'M' ? S7Consts.S7AreaMK : s[0] == 'I' ? S7Consts.S7AreaPE : S7Consts.S7AreaPA;
                string rest = s.Substring(1);
                if (rest.Contains("."))
                {
                    tag.IsBool = true;
                    var parts = rest.Split('.');
                    tag.Start = int.Parse(parts[0]);
                    tag.Bit = int.Parse(parts[1]);
                }
                else tag.Start = int.Parse(rest);
                return tag;
            }
            throw new PlcException("不支持的 S7 地址：" + address);
        }

        private byte[] ReadBytes(S7Tag tag, int size)
        {
            var buf = new byte[size];
            int res;
            if (tag.Area == S7Consts.S7AreaDB) res = _client.DBRead(tag.Db, tag.Start, size, buf);
            else if (tag.Area == S7Consts.S7AreaMK) res = _client.MBRead(tag.Start, size, buf);
            else if (tag.Area == S7Consts.S7AreaPE) res = _client.EBRead(tag.Start, size, buf);
            else res = _client.ABRead(tag.Start, size, buf);
            if (res != 0) throw new PlcException("S7 读失败：" + _client.ErrorText(res));
            return buf;
        }

        private void WriteBytes(S7Tag tag, byte[] buf)
        {
            int res;
            if (tag.Area == S7Consts.S7AreaDB) res = _client.DBWrite(tag.Db, tag.Start, buf.Length, buf);
            else if (tag.Area == S7Consts.S7AreaMK) res = _client.MBWrite(tag.Start, buf.Length, buf);
            else if (tag.Area == S7Consts.S7AreaPA) res = _client.ABWrite(tag.Start, buf.Length, buf);
            else throw new PlcException("该 S7 区域不可写");
            if (res != 0) throw new PlcException("S7 写失败：" + _client.ErrorText(res));
        }

        public bool ReadBool(string address)
        {
            var tag = Parse(address);
            if (!tag.IsBool) throw new PlcException("地址不是位地址：" + address);
            var b = ReadBytes(tag, 1)[0];
            return ((b >> tag.Bit) & 1) != 0;
        }

        public void WriteBool(string address, bool value)
        {
            var tag = Parse(address);
            if (!tag.IsBool) throw new PlcException("地址不是位地址：" + address);
            var b = ReadBytes(tag, 1);
            if (value) b[0] = (byte)(b[0] | (1 << tag.Bit));
            else b[0] = (byte)(b[0] & ~(1 << tag.Bit));
            WriteBytes(tag, b);
        }

        public int ReadInt(string address)
        {
            var tag = Parse(address);
            var b = ReadBytes(tag, 2);
            return S7.GetIntAt(b, 0);
        }

        public void WriteInt(string address, int value)
        {
            var tag = Parse(address);
            var b = new byte[2];
            S7.SetIntAt(b, 0, (short)value);
            WriteBytes(tag, b);
        }

        private void Close()
        {
            if (_client == null) return;
            try { _client.Disconnect(); } catch { }
            _client = null;
        }

        public void Dispose() { Close(); }
    }

    internal class PlcController : IDisposable
    {
        private readonly PlcConfig _cfg;
        private readonly IPlcAdapter _plc;
        private readonly Func<Task<string>> _capture;
        private readonly Func<string, Task<int>> _process;
        private readonly Action<string> _log;
        private readonly System.Threading.Timer _timer;
        private int _busy;
        private bool _lastTrigger;
        private volatile bool _running = true;

        public PlcController(PlcConfig cfg, IPlcAdapter plc,
                             Func<Task<string>> capture, Func<string, Task<int>> process, Action<string> log)
        {
            _cfg = cfg; _plc = plc; _capture = capture; _process = process; _log = log;
            _timer = new System.Threading.Timer(Tick, null, 200, 120);
            _plc.WriteBool(cfg.Ready, true);
            _plc.WriteBool(cfg.Busy, false);
            _plc.WriteBool(cfg.Done, false);
        }

        private async void Tick(object state)
        {
            if (!_running || Interlocked.CompareExchange(ref _busy, 1, 0) != 0) return;
            try
            {
                bool trigger = _plc.ReadBool(_cfg.Trigger);
                if (trigger && !_lastTrigger)
                {
                    _log("PLC 触发，等待相机图像");
                    _plc.WriteBool(_cfg.Ready, false);
                    _plc.WriteBool(_cfg.Busy, true);
                    string image = await _capture();
                    int code = 3;
                    if (image == null) _log("PLC 触发超时：没有新图片");
                    else
                    {
                        code = await _process(image);
                        _log("判定完成，结果码 " + code);
                    }
                    _plc.WriteInt(_cfg.Result, code);
                    _plc.WriteBool(_cfg.Done, true);
                    await Task.Delay(300);
                    _plc.WriteBool(_cfg.Done, false);
                    _plc.WriteBool(_cfg.Busy, false);
                    _plc.WriteBool(_cfg.Ready, true);
                }
                _lastTrigger = trigger;
            }
            catch (Exception ex)
            {
                _log("PLC 握手错误：" + ex.Message);
                try { _plc.WriteBool(_cfg.Error, true); _plc.WriteInt(_cfg.Result, 3); } catch { }
            }
            finally { Interlocked.Exchange(ref _busy, 0); }
        }

        public void Dispose()
        {
            _running = false;
            _timer.Dispose();
            try { _plc.WriteBool(_cfg.Ready, false); _plc.WriteBool(_cfg.Busy, false); } catch { }
            _plc.Dispose();
        }
    }

    internal static class CameraWait
    {
        public static async Task<string> WaitForNewImage(string dir, DateTime since, int timeoutMs)
        {
            var exts = new[] { ".png", ".jpg", ".jpeg", ".bmp" };
            var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            while (DateTime.UtcNow < deadline)
            {
                if (Directory.Exists(dir))
                {
                    var best = Directory.GetFiles(dir)
                        .Where(f => exts.Contains(Path.GetExtension(f).ToLowerInvariant()))
                        .Where(f => File.GetLastWriteTimeUtc(f) >= since)
                        .OrderByDescending(f => File.GetLastWriteTimeUtc(f))
                        .FirstOrDefault();
                    if (best != null) return best;
                }
                await Task.Delay(100);
            }
            return null;
        }
    }
}
