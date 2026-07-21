cmake_minimum_required(VERSION 3.10)
project(smartbag_ss928_acl LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

set(SS928_NPU_INCLUDE_DIR "" CACHE PATH "Directory containing acl.h")
set(SS928_NPU_LIBRARY "" CACHE FILEPATH "SS928 libascendcl.so used for linking")
if(NOT EXISTS "${SS928_NPU_INCLUDE_DIR}/acl.h")
    message(FATAL_ERROR "Set SS928_NPU_INCLUDE_DIR to the SS928 SDK NPU include directory")
endif()
if(NOT EXISTS "${SS928_NPU_LIBRARY}")
    message(FATAL_ERROR "Set SS928_NPU_LIBRARY to the SS928 SDK libascendcl.so")
endif()

add_library(smartbag_ss928_acl SHARED smartbag_ss928_acl.cpp)
target_include_directories(smartbag_ss928_acl PRIVATE "${SS928_NPU_INCLUDE_DIR}")
target_link_libraries(smartbag_ss928_acl PRIVATE "${SS928_NPU_LIBRARY}")
set_target_properties(smartbag_ss928_acl PROPERTIES
    OUTPUT_NAME smartbag_ss928_acl
    INSTALL_RPATH "/opt/lib/npu:/opt/lib"
)

install(TARGETS smartbag_ss928_acl LIBRARY DESTINATION lib)
