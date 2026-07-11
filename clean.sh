#!/bin/bash

echo "================================"
echo "   Nanobanana 清理工具"
echo "================================"
echo ""

# 清理上传的参考视频
if [ -d "upload_video" ]; then
    count=$(find upload_video -type f | wc -l)
    rm -rf upload_video/*
    echo "✓ 已清理 upload_video/ ($count 个文件)"
else
    echo "- upload_video/ 不存在，跳过"
fi

# 清理输出目录
if [ -d "output" ]; then
    count=$(find output -type f | wc -l)
    rm -rf output/*
    echo "✓ 已清理 output/ ($count 个文件)"
else
    echo "- output/ 不存在，跳过"
fi

# 清理错误日志
if [ -d "error_logs" ]; then
    count=$(find error_logs -type f | wc -l)
    rm -rf error_logs/*
    echo "✓ 已清理 error_logs/ ($count 个文件)"
else
    echo "- error_logs/ 不存在，跳过"
fi

# 清理任务数据库
if [ -f "tasks.db" ]; then
    rm -f tasks.db tasks.db-shm tasks.db-wal
    echo "✓ 已清理 tasks.db"
else
    echo "- tasks.db 不存在，跳过"
fi

# 清理日志文件
rm -f server.log worker.log client.log
echo "✓ 已清理日志文件"

echo ""
echo "================================"
echo "   清理完成！"
echo "================================"
