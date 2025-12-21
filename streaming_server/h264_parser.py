"""H264流解析器：从裸H264流中检测关键帧（IDR帧）"""

from typing import List, Tuple


class H264StreamParser:
    """解析H264裸流，检测关键帧位置"""
    
    def __init__(self):
        # NAL单元起始码：0x00 0x00 0x00 0x01 或 0x00 0x00 0x01
        self.start_code_3 = b'\x00\x00\x01'
        self.start_code_4 = b'\x00\x00\x00\x01'
        self.buffer = b''  # 缓冲区，处理跨包的NAL单元
        
    def find_nal_units(self, data: bytes) -> List[Tuple[int, int, int]]:
        """
        从H264数据中查找所有NAL单元
        
        Args:
            data: H264数据
            
        Returns:
            List[(nal_type, offset, length)] - NAL类型、在数据中的偏移、长度
        """
        # 合并缓冲区和新数据
        combined = self.buffer + data
        nals = []
        i = 0
        
        while i < len(combined):
            # 查找起始码
            start_pos = None
            if i + 4 <= len(combined) and combined[i:i+4] == self.start_code_4:
                start_pos = i
                i += 4
            elif i + 3 <= len(combined) and combined[i:i+3] == self.start_code_3:
                start_pos = i
                i += 3
            else:
                i += 1
                continue
            
            # 查找下一个起始码或数据结束
            end_pos = len(combined)
            for j in range(i, len(combined) - 2):
                if (j + 4 <= len(combined) and combined[j:j+4] == self.start_code_4) or \
                   (j + 3 <= len(combined) and combined[j:j+3] == self.start_code_3):
                    end_pos = j
                    break
            
            # 提取NAL单元
            nal_data = combined[start_pos:end_pos]
            if len(nal_data) > 4:
                # NAL类型在起始码后的第一个字节的低5位
                # 对于4字节起始码，NAL类型在索引4；对于3字节起始码，在索引3
                nal_type_byte_index = 4 if combined[start_pos:start_pos+4] == self.start_code_4 else 3
                if nal_type_byte_index < len(nal_data):
                    nal_type = nal_data[nal_type_byte_index] & 0x1F
                    nals.append((nal_type, start_pos, len(nal_data)))
            
            i = end_pos
        
        # 保留未完成的NAL单元到缓冲区
        # 检查最后是否有未完成的起始码（距离末尾小于10字节）
        if len(combined) > 0:
            last_start_3 = combined.rfind(self.start_code_3, 0, len(combined) - 3)
            last_start_4 = combined.rfind(self.start_code_4, 0, len(combined) - 4)
            last_start = max(last_start_3, last_start_4)
            
            if last_start > len(combined) - 10:  # 如果起始码太靠近末尾
                self.buffer = combined[last_start:]
            else:
                self.buffer = b''
        else:
            self.buffer = b''
        
        return nals
    
    def is_keyframe(self, nal_type: int) -> bool:
        """
        判断NAL单元是否为关键帧
        
        Args:
            nal_type: NAL类型
            
        Returns:
            True 如果是IDR帧（关键帧），否则 False
        """
        # IDR帧：NAL类型为5
        return nal_type == 5
    
    def is_sps(self, nal_type: int) -> bool:
        """判断NAL单元是否为SPS（序列参数集）"""
        return nal_type == 7
    
    def is_pps(self, nal_type: int) -> bool:
        """判断NAL单元是否为PPS（图像参数集）"""
        return nal_type == 8
    
    def extract_nal_unit(self, data: bytes, start_pos: int, length: int) -> bytes:
        """从数据中提取完整的NAL单元（包含起始码）"""
        if start_pos + length <= len(data):
            return data[start_pos:start_pos + length]
        return b''
    
    def extract_nal_units_from_data(self, data: bytes) -> List[Tuple[int, bytes]]:
        """
        从H264数据中提取所有NAL单元及其类型
        
        Args:
            data: H264数据
            
        Returns:
            List[(nal_type, nal_data)] - NAL类型和完整的NAL单元数据（包含起始码）
        """
        nals = self.find_nal_units(data)
        result = []
        combined = self.buffer + data
        
        for nal_type, offset, length in nals:
            if offset + length <= len(combined):
                nal_data = combined[offset:offset + length]
                # 重新验证NAL类型，确保类型与数据一致
                actual_nal_type = None
                if nal_data.startswith(b'\x00\x00\x00\x01'):
                    if len(nal_data) > 4:
                        actual_nal_type = nal_data[4] & 0x1F
                elif nal_data.startswith(b'\x00\x00\x01'):
                    if len(nal_data) > 3:
                        actual_nal_type = nal_data[3] & 0x1F
                
                # 如果实际类型与返回类型不匹配，使用实际类型
                if actual_nal_type is not None and actual_nal_type != nal_type:
                    print(f"[Warning] NAL类型不匹配：返回类型={nal_type}, 实际类型={actual_nal_type}, 使用实际类型")
                    nal_type = actual_nal_type
                
                result.append((nal_type, nal_data))
        
        return result
    
    def reset(self):
        """重置缓冲区"""
        self.buffer = b''

