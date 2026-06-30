import cv2
import numpy as np
import time
import requests
import threading
from datetime import datetime
import os
import sys
from PIL import Image, ImageDraw, ImageFont

def put_chinese_text(img, text, pos, scale=1.0, color=(255, 255, 255)):
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    font_path = "C:/Windows/Fonts/simhei.ttf"
    try:
        font = ImageFont.truetype(font_path, int(24 * scale))
    except:
        font = ImageFont.load_default()
    draw.text(pos, text, font=font, fill=color)
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

class MotionDetector:
    def __init__(self, url, camera_name="Please enter the name of camera", threshold=5000, min_area=500, save_dir="motion_captures"):
        self.url = url
        self.camera_name = camera_name
        self.threshold = threshold
        self.min_area = min_area
        self.save_dir = save_dir
        self.cap = None
        self.background = None
        self.is_moving = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.last_frame_time = time.time()
        self.frame_timeout = 8
        self.keep_alive_running = True
        self.heartbeat_interval = 25
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            print(f"[{self.get_time()}] 创建照片保存目录: {save_dir}")
        self.total_motion_events = 0
        self.auto_save_count = 0
        self.manual_save_count = 0
        self.heartbeat_count = 0
        
    def get_time(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def get_filename(self, prefix="motion"):
        now = datetime.now()
        filename = f"{prefix}_{now.strftime('%Y%m%d_%H%M%S_%f')[:-3]}.jpg"
        return filename
    
    def keep_alive_heartbeat(self):
        print(f"[{self.get_time()}] 心跳线程已启动（间隔{self.heartbeat_interval}秒）")
        endpoints = [
            self.url,
            self.url.replace('/video', '/'),
            self.url.replace('/video', '/status'),
            self.url.replace('/video', '/ping'),
        ]
        while self.keep_alive_running:
            try:
                self.heartbeat_count += 1
                response = None
                for endpoint in endpoints:
                    try:
                        response = requests.head(
                            endpoint, 
                            timeout=3,
                            auth=requests.auth.HTTPBasicAuth('admin', '12345678')
                        )
                        if response.status_code in [200, 401]:
                            break
                    except:
                        continue
                if self.heartbeat_count % 10 == 0:
                    print(f"[{self.get_time()}] 心跳 #{self.heartbeat_count} - 平板在线")
            except requests.exceptions.Timeout:
                print(f"[{self.get_time()}] 心跳超时，平板可能进入休眠")
            except requests.exceptions.ConnectionError:
                print(f"[{self.get_time()}] 心跳连接失败，平板可能离线")
            except Exception as e:
                if self.heartbeat_count % 10 == 0:
                    print(f"[{self.get_time()}] 心跳异常: {e}")
            time.sleep(self.heartbeat_interval)
        print(f"[{self.get_time()}] 心跳线程已停止")
    
    def connect(self):
        print(f"[{self.get_time()}] 正在连接监控摄像头...")
        try:
            wake_response = requests.get(
                self.url, 
                timeout=5,
                auth=requests.auth.HTTPBasicAuth('admin', '12345678'),
                stream=True
            )
            if wake_response.status_code == 200:
                print(f"[{self.get_time()}] 唤醒请求已发送")
            wake_response.close()
        except:
            pass
        if self.cap is not None:
            self.cap.release()
        self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap.set(cv2.CAP_PROP_FPS, 15)
        if not self.cap.isOpened():
            self.reconnect_attempts += 1
            print(f"[{self.get_time()}] 连接失败 ({self.reconnect_attempts}/{self.max_reconnect_attempts})")
            if self.reconnect_attempts <= self.max_reconnect_attempts:
                wait_time = min(3, self.reconnect_attempts)
                time.sleep(wait_time)
                return self.connect()
            return False
        for _ in range(5):
            self.cap.grab()
        self.reconnect_attempts = 0
        self.last_frame_time = time.time()
        print(f"[{self.get_time()}] 连接成功！")
        return True
    
    def read_frame_with_timeout(self, timeout=5):
        start_time = time.time()
        while time.time() - start_time < timeout:
            ret, frame = self.cap.read()
            if ret:
                self.last_frame_time = time.time()
                return True, frame
            time.sleep(0.01)
        return False, None
    
    def check_and_reconnect(self):
        now = time.time()
        if now - self.last_frame_time > self.frame_timeout:
            print(f"[{self.get_time()}] 检测到连接超时（{now - self.last_frame_time:.1f}秒无新帧）")
            print(f"[{self.get_time()}] 尝试重新连接...")
            if self.cap:
                self.cap.release()
            return self.connect()
        return True
    
    def save_motion_photo(self, frame, motion_info=None):
        if motion_info is None:
            motion_info = {'area_count': 1, 'max_area': 0}
        img_with_info = frame.copy()
        info_lines = [
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}",
            f"Motion Areas: {motion_info.get('area_count', 1)}",
            f"Max Area: {motion_info.get('max_area', 0):.0f} px"
        ]
        for i, line in enumerate(info_lines):
            cv2.putText(img_with_info, line, (10, 30 + i*25), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        h, w = img_with_info.shape[:2]
        img_with_info = put_chinese_text(img_with_info, self.camera_name, (w - 220, h - 20), 0.7)
        filename = self.get_filename("motion")
        filepath = os.path.join(self.save_dir, filename)
        success = cv2.imwrite(filepath, img_with_info)
        if success:
            self.auto_save_count += 1
            file_size = os.path.getsize(filepath) / 1024
            print(f"   已保存: {filename} ({file_size:.1f} KB)")
            return filepath
        return None
    
    def detect_motion(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        if self.background is None:
            self.background = gray.copy().astype(np.float32)
            return False, frame
        gray_float = gray.astype(np.float32)
        diff = cv2.absdiff(gray_float, self.background)
        diff_uint8 = diff.astype(np.uint8)
        _, thresh = cv2.threshold(diff_uint8, 25, 255, cv2.THRESH_BINARY)
        thresh = cv2.dilate(thresh, None, iterations=2)
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, 
                                       cv2.CHAIN_APPROX_SIMPLE)
        motion_detected = False
        motion_areas = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > self.min_area:
                motion_detected = True
                motion_areas.append(area)
                x, y, w, h = cv2.boundingRect(contour)
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 2)
        cv2.accumulateWeighted(gray, self.background, 0.5)
        if motion_detected:
            current_time = self.get_time()
            total_area = sum(motion_areas)
            max_area = max(motion_areas) if motion_areas else 0
            motion_info = {
                'area_count': len(motion_areas),
                'max_area': max_area,
                'total_area': total_area
            }
            if not self.is_moving:
                self.is_moving = True
                self.total_motion_events += 1
                print(f"\n{'='*60}")
                print(f"[{current_time}] 检测到运动开始！")
                print(f"   区域数量: {len(motion_areas)} 个")
                print(f"   最大面积: {max_area:.0f} 像素")
                print(f"   总面积: {total_area:.0f} 像素")
                self.save_motion_photo(frame, motion_info)
                print(f"{'='*60}")
            else:
                if int(time.time()) % 30 < 1:
                    self.save_motion_photo(frame, motion_info)
        else:
            if self.is_moving:
                print(f"\n[{self.get_time()}] 运动结束")
                print(f"{'='*60}\n")
                self.is_moving = False
        status_text = f"Motion: {'YES' if motion_detected else 'NO'}"
        cv2.putText(frame, status_text, (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                   (0, 0, 255) if motion_detected else (0, 255, 0), 2)
        time_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, time_text, (10, 60), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(frame, f"Heartbeat: {self.heartbeat_count}", 
                   (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        h, w = frame.shape[:2]
        frame = put_chinese_text(frame, self.camera_name, (w - 220, h - 20), 0.7)
        return motion_detected, frame
    
    def print_statistics(self):
        print(f"\n{'='*60}")
        print(f"运行统计")
        print(f"{'='*60}")
        print(f"   检测到运动事件: {self.total_motion_events} 次")
        print(f"   自动保存照片: {self.auto_save_count} 张")
        print(f"   手动保存照片: {self.manual_save_count} 张")
        print(f"   心跳请求次数: {self.heartbeat_count} 次")
        print(f"   照片保存目录: {os.path.abspath(self.save_dir)}")
        print(f"{'='*60}")
    
    def run(self):
        if not self.connect():
            print("无法连接摄像头，请检查网络和地址")
            return False
        heartbeat_thread = threading.Thread(target=self.keep_alive_heartbeat, daemon=True)
        heartbeat_thread.start()
        print(f"\n[{self.get_time()}] 监控系统运行中...")
        print("提示：")
        print("  'q' - 退出程序")
        print("  's' - 保存当前画面")
        print("  'h' - 手动发送心跳唤醒")
        print(f"  心跳间隔: {self.heartbeat_interval} 秒\n")
        consecutive_failures = 0
        while True:
            if not self.check_and_reconnect():
                time.sleep(2)
                continue
            ret, frame = self.read_frame_with_timeout(timeout=5)
            if not ret:
                consecutive_failures += 1
                print(f"[{self.get_time()}] 读帧失败 ({consecutive_failures}/3)")
                if consecutive_failures >= 3:
                    print(f"[{self.get_time()}] 连续失败，触发重连...")
                    self.connect()
                    consecutive_failures = 0
                continue
            consecutive_failures = 0
            try:
                motion_detected, display_frame = self.detect_motion(frame)
            except Exception as e:
                print(f"[{self.get_time()}] 运动检测错误: {e}")
                display_frame = frame
            cv2.imshow('IP Camera', display_frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print(f"\n[{self.get_time()}] 用户退出监控系统")
                break
            elif key == ord('s'):
                self.manual_save_count += 1
                filename = f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                filepath = os.path.join(self.save_dir, filename)
                cv2.imwrite(filepath, display_frame)
                print(f"[{self.get_time()}] 手动保存: {filename}")
            elif key == ord('h'):
                print(f"[{self.get_time()}] 手动发送心跳唤醒...")
                try:
                    requests.get(self.url, timeout=3, 
                               auth=requests.auth.HTTPBasicAuth('admin', '12345678'))
                    print(f"[{self.get_time()}] 心跳发送成功")
                except Exception as e:
                    print(f"[{self.get_time()}] 心跳发送失败: {e}")
        self.keep_alive_running = False
        heartbeat_thread.join(timeout=2)
        self.cap.release()
        cv2.destroyAllWindows()
        self.print_statistics()
        return True

def main():
    print("="*60)
    print("IP Camera - 监控系统")
    print("="*60)
    
    ip_address = input("请输入摄像头IP地址 (默认: 192.168.1.1): ").strip()
    if not ip_address:
        ip_address = "192.168.1.1"
    
    camera_name = input("请输入摄像头名称 (默认: Please enter the name of camera): ").strip()
    if not camera_name:
        camera_name = "Please enter the name of camera"
    
    url = f"http://admin:12345678@{ip_address}:8081/video"
    
    print(f"\n摄像头IP: {ip_address}")
    print(f"摄像头名称: {camera_name}")
    print(f"视频地址: {url}\n")
    
    detector = MotionDetector(
        url=url,
        camera_name=camera_name,
        threshold=5000,  
        min_area=500,    
        save_dir="motion_captures"  
    )
    
    try:
        detector.run()
    except KeyboardInterrupt:
        print(f"\n[{detector.get_time()}] 程序被用户中断")
        detector.print_statistics()
    except Exception as e:
        print(f"[{detector.get_time()}] 发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()