"""字段加密服务（混合加密：AES-GCM + RSA-OAEP）"""

import base64
import secrets
from typing import Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes


class FieldEncryptionService:
    """字段加密服务"""
    
    def __init__(self, aes_key_size: int = 32):
        """
        初始化加密服务
        
        Args:
            aes_key_size: AES 密钥长度（字节），32 = AES-256
        """
        self.aes_key_size = aes_key_size
    
    def encrypt_field_value(self, event_id: str, field_path: str, value: str,
                           user_id: str, public_key_pem: str) -> Tuple[str, str]:
        """
        加密字段值（混合加密）
        
        流程：
        1. 生成 DEK（AES-256 密钥）
        2. 用 DEK 加密字段值（AES-GCM）
        3. 用用户公钥加密 DEK（RSA-OAEP）
        4. 返回加密后的字段值和 encrypted_dek
        
        Args:
            event_id: 事件 ID
            field_path: 字段路径（如 'person.clothing_color'）
            value: 要加密的字段值
            user_id: 用户 ID
            public_key_pem: 用户公钥（PEM 格式）
        
        Returns:
            (encrypted_value, encrypted_dek) 元组
            - encrypted_value: 加密后的字段值（Base64 编码的字符串，包含 nonce + ciphertext）
            - encrypted_dek: 加密后的 DEK（Base64 编码的字符串）
        """
        # 1. 生成 DEK（AES-256）
        dek = secrets.token_bytes(self.aes_key_size)
        
        # 2. 用 DEK 加密值（AES-GCM，自动处理认证）
        aesgcm = AESGCM(dek)
        nonce = secrets.token_bytes(12)  # GCM 推荐 12 字节 nonce
        encrypted_value_bytes = aesgcm.encrypt(
            nonce,
            value.encode('utf-8'),
            None  # 不使用 associated data
        )
        
        # 将 nonce + encrypted_value 拼接后 Base64 编码
        encrypted_value = base64.b64encode(nonce + encrypted_value_bytes).decode('utf-8')
        
        # 3. 用用户公钥加密 DEK（RSA-OAEP）
        try:
            public_key = serialization.load_pem_public_key(public_key_pem.encode())
        except Exception as e:
            raise ValueError(f"无法加载公钥: {e}")
        
        try:
            encrypted_dek_bytes = public_key.encrypt(
                dek,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            encrypted_dek = base64.b64encode(encrypted_dek_bytes).decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"加密 DEK 失败: {e}")
        
        return encrypted_value, encrypted_dek
    
    def decrypt_field_value(self, event_id: str, field_path: str,
                           encrypted_value: str, user_id: str,
                           private_key_pem: str) -> str:
        """
        解密字段值（需要用户的私钥）
        
        流程：
        1. 从数据库获取 encrypted_dek（由调用者提供）
        2. 用用户私钥解密 DEK
        3. 用 DEK 解密字段值
        
        Args:
            event_id: 事件 ID
            field_path: 字段路径
            encrypted_value: 加密后的字段值（Base64）
            user_id: 用户 ID
            private_key_pem: 用户私钥（PEM 格式）
        
        Returns:
            解密后的明文字段值
        """
        # 1. 从 Base64 解码
        encrypted_value_bytes = base64.b64decode(encrypted_value)
        nonce = encrypted_value_bytes[:12]
        ciphertext = encrypted_value_bytes[12:]
        
        # 2. 注意：这里需要调用者提供 encrypted_dek
        # 因为加密服务不应该直接访问数据库
        # 这个方法需要配合外部传入的 encrypted_dek 使用
        raise NotImplementedError(
            "解密需要从数据库获取 encrypted_dek，请使用 decrypt_field_value_with_dek 方法"
        )
    
    def decrypt_field_value_with_dek(self, encrypted_value: str,
                                    encrypted_dek: str,
                                    private_key_pem: str) -> str:
        """
        使用已获取的 encrypted_dek 解密字段值
        
        Args:
            encrypted_value: 加密后的字段值（Base64）
            encrypted_dek: 加密后的 DEK（Base64）
            private_key_pem: 用户私钥（PEM 格式）
        
        Returns:
            解密后的明文字段值
        """
        # 1. 用私钥解密 DEK
        try:
            private_key = serialization.load_pem_private_key(
                private_key_pem.encode(),
                password=None
            )
        except Exception as e:
            raise ValueError(f"无法加载私钥: {e}")
        
        try:
            dek_bytes = base64.b64decode(encrypted_dek)
            dek = private_key.decrypt(
                dek_bytes,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
        except Exception as e:
            raise RuntimeError(f"解密 DEK 失败: {e}")
        
        # 2. 用 DEK 解密字段值
        encrypted_value_bytes = base64.b64decode(encrypted_value)
        nonce = encrypted_value_bytes[:12]
        ciphertext = encrypted_value_bytes[12:]
        
        try:
            aesgcm = AESGCM(dek)
            decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"解密字段值失败: {e}")

