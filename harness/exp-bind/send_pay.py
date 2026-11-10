import json,socket,sys
host=sys.argv[1]; token=open(sys.argv[2]).read().strip(); declared=sys.argv[3]; amount=int(sys.argv[4])
s=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM)
s.sendto(json.dumps({'token':token,'declared_payer':declared,'amount_sat':amount}).encode(),(host,2122))
